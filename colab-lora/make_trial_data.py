"""사전 GPU 시험용 합성 train.jsonl을 만든다 (C단계 합의 12 — 최장 prefix·최대 대상 부하).

실제 반출 데이터는 폐쇄망 배포 뒤에야 쌓인다. 시험은 품질이 아니라 커널·메모리·NF4 제외 목록·Q6_K 적재를
본다. 그래서 B단계 추출기 형식의 샘플 하나(예: tests/fixtures 세션을 export한 것)를 바탕으로 도구 결과·응답
본문을 채워, 요청 prefix가 목표 토큰 수에 가까운 샘플들을 만든다. 같은 이름의 .report.md에 sha256을 적어
run.sh의 데이터 대조를 그대로 통과하게 한다. **반출 데이터가 아니다.**

    python colab-lora/make_trial_data.py --base train.jsonl --tokenizer Qwen/Qwen3.8-27B --out trial.jsonl
    colab-lora/run.sh trial trial.jsonl trial.report.md --max-seq-len 65536 --holdout 0
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataset  # noqa: E402

FILLER = "def step_{i}(values):\n    total = sum(v * {i} for v in values)\n    return total % 97\n\n"


def filler(n: int) -> str:
    return "".join(FILLER.format(i=i) for i in range(n))


def build(base: dict, name: str, tool_units: int, reply_units: int) -> dict:
    sample = copy.deepcopy(base)
    sample["session_id"] = f"trial-{name}"
    sample["segment"] = 0
    tool = next(i for i, m in enumerate(sample["messages"]) if m["role"] == "tool")
    last = max(sample["train_indices"])
    if tool_units:
        sample["messages"][tool]["content"] = filler(tool_units)
    if reply_units:
        sample["messages"][last]["content"] = filler(reply_units)
    return sample


def measure(sample: dict, render, encode) -> tuple[int, int]:
    sequences, stats = dataset.build_sequences(sample, render, encode, 10**9)
    return stats.max_sequence_tokens, stats.target_tokens


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", type=Path, required=True, help="B단계 추출기 형식 train.jsonl(첫 줄을 바탕으로 쓴다)")
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--template", type=Path, default=Path(__file__).with_name("qwen38_chat_template.jinja"))
    args = p.parse_args(argv)

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)
    template = args.template.read_text(encoding="utf-8")
    dataset.check_template(template, tokenizer)
    render, encode = dataset.hf_functions(tokenizer, template)
    base = dataset.load_samples(args.base)[0]
    unit = len(encode(FILLER.format(i=12345)))

    # 길이 사다리: train.py --trial이 긴 것부터 내려가며 OOM이 아닌 첫 길이를 찾는다(A100 40GB 등 작은 GPU 대응).
    plans = [("short", None, None), ("targets-8k", "targets", 8000)] + [
        (f"prefix-{k}k", "prefix", k * 1000 - 1000) for k in (8, 12, 16, 20, 24, 32, 48, 63)]
    samples, rows = [], []
    for name, kind, goal in plans:
        units = 0
        base_len, base_targets = measure(build(base, name, 0, 0), render, encode)
        for _ in range(3):  # 반복 단위의 토큰 수가 번호 자릿수에 따라 달라 비례 보정한다
            if kind is None:
                break
            sample = build(base, name, units if kind == "prefix" else 0, units if kind == "targets" else 0)
            length, targets = measure(sample, render, encode)
            now, start = (length, base_len) if kind == "prefix" else (targets, base_targets)
            per_unit = (now - start) / units if units else unit
            units = max(1, int((goal - start) / per_unit))
        sample = build(base, name, units if kind == "prefix" else 0, units if kind == "targets" else 0)
        length, targets = measure(sample, render, encode)
        samples.append(sample)
        rows.append({"session_id": sample["session_id"], "max_sequence_tokens": length, "target_tokens": targets})

    data = "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in samples).encode("utf-8")
    args.out.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    report = args.out.with_suffix(".report.md")
    report.write_text("# 사전 GPU 시험용 합성 데이터 (반출 데이터 아님)\n\n"
                      f"- 파일: `{args.out.name}` {len(data):,} bytes\n- sha256: `{digest}`\n- 바탕: `{args.base.name}` 첫 샘플\n\n"
                      + "".join(f"- {r['session_id']}: 시퀀스 {r['max_sequence_tokens']:,} 토큰, 학습 대상 {r['target_tokens']:,} 토큰\n" for r in rows),
                      encoding="utf-8")
    print(json.dumps({"out": str(args.out), "sha256": digest, "samples": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
