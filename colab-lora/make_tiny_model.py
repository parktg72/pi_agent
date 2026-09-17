"""원본 Qwen/Qwen3.8-27B와 같은 구조를 줄인 초소형 랜덤 모델을 만든다 (GPU 비용 전 CPU 리허설용).

Qwen3_5ForConditionalGeneration(language_model + visual + mtp 15텐서), linear 키/값 헤드 비 1:3, 원본 토크나이저·
chat_template. 가중치는 랜덤이라 품질과 무관하다 — Colab 이미지의 패키지 조합에서 train.py의 peft 적용·데이터·
checkpoint 경로가 도는지(예: 기본 설치 torchao와 peft 충돌, 2026-09-18 A100 실측)를 GPU 전에 본다.

    python make_tiny_model.py --out tiny
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BASE_MODEL = "Qwen/Qwen3.8-27B"
BASE_REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
FILES = ["config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt", "chat_template.jinja",
         "generation_config.json", "preprocessor_config.json", "video_preprocessor_config.json"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--revision", default=BASE_REVISION)
    args = p.parse_args(argv)

    import shutil

    import torch
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file, save_file
    from transformers import AutoConfig, Qwen3_5ForConditionalGeneration

    args.out.mkdir(parents=True, exist_ok=True)
    source = {name: Path(hf_hub_download(BASE_MODEL, name, revision=args.revision)) for name in FILES}
    config = json.loads(source["config.json"].read_text(encoding="utf-8"))
    text = config["text_config"]
    text.update(hidden_size=64, intermediate_size=128, num_hidden_layers=4, num_attention_heads=4, num_key_value_heads=2,
                head_dim=16, linear_num_key_heads=2, linear_num_value_heads=6, linear_key_head_dim=8, linear_value_head_dim=8,
                layer_types=["linear_attention"] * 3 + ["full_attention"], max_position_embeddings=65536, mtp_num_hidden_layers=1)
    text["rope_parameters"]["mrope_section"] = [1, 1, 0]
    config["vision_config"].update(depth=1, hidden_size=32, intermediate_size=64, num_heads=2, out_hidden_size=64, num_position_embeddings=16)
    config["dtype"] = "float32"
    (args.out / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    torch.manual_seed(0)
    model = Qwen3_5ForConditionalGeneration(AutoConfig.from_pretrained(args.out)).to(torch.float32)
    model.save_pretrained(args.out, safe_serialization=True)
    for name in FILES[1:]:
        shutil.copy(source[name], args.out / name)
    # transformers는 mtp 모듈을 만들지 않는다 - 실제 체크포인트처럼 mtp.* 15텐서를 채운다(full-attn 층 3을 본뜸).
    weights = args.out / "model.safetensors"
    tensors = load_file(weights)
    for key in list(tensors):
        if key.startswith("model.language_model.layers.3."):
            tensors["mtp.layers.0." + key[len("model.language_model.layers.3."):]] = tensors[key].clone()
    hidden = text["hidden_size"]
    tensors["mtp.fc.weight"] = torch.randn(hidden, 2 * hidden) * 0.02
    for name in ("norm", "pre_fc_norm_embedding", "pre_fc_norm_hidden"):
        tensors[f"mtp.{name}.weight"] = torch.ones(hidden)
    save_file(tensors, weights, metadata={"format": "pt"})
    print(json.dumps({"event": "done", "out": str(args.out), "tensors": len(tensors)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
