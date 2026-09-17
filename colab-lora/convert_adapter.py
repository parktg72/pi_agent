"""Colab에서 받은 PEFT 어댑터를 llama.cpp b11010 GGUF LoRA로 바꾼다 (개발 PC CPU, C단계 합의 8).

- 변환기는 번들 llama.cpp와 같은 태그(b11010)의 convert_lora_to_gguf.py만 쓴다. `--no-nextn`은 이 스크립트에
  없고 쓰지 않는다 - 원본 config(mtp_num_hidden_layers 1)대로 block_count 65가 번들 Q6_K와 같다.
- 변환 전: adapter_config의 base 모델·대상 모듈, 어댑터 텐서 이름(out_proj·visual·mtp 금지)을 검사한다.
- 변환 후: GGUF의 architecture(qwen35)·adapter 종류·텐서 수가 어댑터와 맞는지 보고, sha256을 적는다.
- 반입 파일 이름은 config.env LORA_FILE 규칙([A-Za-z0-9._-]+.gguf)을 따라야 한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

LLAMA_CPP_TAG = "b11010"
FORBIDDEN = ("out_proj", "visual", "mtp")
LORA_FILE_NAME = re.compile(r"^[A-Za-z0-9._-]+\.gguf$")


def fail(message: str) -> int:
    print(f"[FAIL] {message}", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="PEFT 어댑터 -> GGUF LoRA (llama.cpp b11010)")
    p.add_argument("adapter", type=Path, help="adapter_config.json·adapter_model.safetensors 폴더")
    p.add_argument("out", type=Path, help="출력 .gguf (lora\\ 에 그대로 넣을 이름)")
    p.add_argument("--base", type=Path, required=True, help="원본 config.json·토크나이저 폴더(가중치 불필요)")
    p.add_argument("--llama-cpp", type=Path, required=True, help=f"llama.cpp {LLAMA_CPP_TAG} 체크아웃")
    p.add_argument("--outtype", default="f16", choices=["f16", "bf16", "f32", "q8_0"])
    args = p.parse_args(argv)

    if not LORA_FILE_NAME.match(args.out.name):
        return fail(f"출력 이름 {args.out.name}은 config.env LORA_FILE 규칙([A-Za-z0-9._-]+.gguf)에 맞지 않는다")
    tag = subprocess.run(["git", "-C", str(args.llama_cpp), "describe", "--tags", "--exact-match"], capture_output=True, text=True)
    if tag.stdout.strip() != LLAMA_CPP_TAG:
        return fail(f"llama.cpp 체크아웃이 {LLAMA_CPP_TAG}가 아니다: {tag.stdout.strip() or tag.stderr.strip()}")

    config = json.loads((args.adapter / "adapter_config.json").read_text(encoding="utf-8"))
    from safetensors import safe_open

    with safe_open(str(args.adapter / "adapter_model.safetensors"), "pt") as handle:
        names = list(handle.keys())
    bad = [name for name in names if any(word in name for word in FORBIDDEN)]
    if not names or bad:
        return fail(f"어댑터 텐서 {len(names)}개, 금지 대상 {bad[:3]}")
    if any(".language_model." not in name for name in names):
        return fail("language_model 밖 텐서가 있다")

    sys.path.insert(0, str(args.llama_cpp / "gguf-py"))
    cmd = [sys.executable, str(args.llama_cpp / "convert_lora_to_gguf.py"), str(args.adapter), "--base", str(args.base),
           "--outtype", args.outtype, "--outfile", str(args.out)]
    print("[run]", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-4000:], result.stderr[-4000:], file=sys.stderr)
        return fail(f"convert_lora_to_gguf 종료코드 {result.returncode}")

    import gguf

    reader = gguf.GGUFReader(str(args.out))
    fields = {key: reader.fields[key].contents() for key in ("general.architecture", "general.type", "adapter.type") if key in reader.fields}
    count = len(reader.tensors)
    if fields.get("general.architecture") != "qwen35" or fields.get("adapter.type") != "lora" or count != len(names):
        return fail(f"GGUF 확인 실패: {fields}, 텐서 {count} != 어댑터 {len(names)}")
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    summary = {"gguf": str(args.out), "bytes": args.out.stat().st_size, "sha256": digest, "tensors": count,
               "base_model": config.get("base_model_name_or_path"), "r": config.get("r"), "lora_alpha": config.get("lora_alpha"),
               "llama_cpp": LLAMA_CPP_TAG, **fields}
    args.out.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
