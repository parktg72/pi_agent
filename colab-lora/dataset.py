"""export-sessions.bat의 train.jsonl → LoRA 학습 시퀀스(input_ids, labels).

개발 PC와 Colab VM이 같은 코드를 쓴다(개발 PC: 반출 전 점검, VM: 학습). 규칙은
tasks/pi-agent-lora-upgrade/artifacts/c-consensus.md 합의 2·3·7을 따른다.

- 샘플의 학습 대상은 train_indices가 가리키는 assistant 응답뿐이다. 앞 구간 응답은 문맥이다.
- 응답 k의 요청 입력 prefix_k = render(messages[:k], generation prompt), 대상 target_k =
  render(messages[:k+1])에서 prefix_k 뒤 `<|im_end|>`까지.
- 시퀀스는 조각별로 토큰화해 잇는다. 전체 문자열을 한 번에 토큰화하면 "<think>\\n"과 빈
  reasoning 응답의 첫 "\\n"이 한 토큰으로 합쳐져, 추론에서는 생성될 수 없는 토큰을 학습한다
  (sources/c-tokenization-finding.md).
- 대상마다 공유 시퀀스의 앞부분이 tok(prefix_k)(llama-server가 받는 요청 전체 토큰화)와 같은지
  검사한다. 다르면 그 대상은 공유 시퀀스에서 라벨을 빼고 tok(prefix_k) + tok(target_k) 별도
  시퀀스로 학습한다.
- max_seq_len을 넘는 대상은 자르지 않고 보류한다. 뒤 대상일수록 prefix가 길어지므로 처음
  넘친 대상부터 끝까지 보류된다.
- 평가 분할은 샘플(구간)이 아니라 세션 단위다. 같은 세션의 구간은 문맥이 겹쳐 검증 점수가
  부풀려진다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

IM_END = "<|im_end|>"
IGNORE = -100
REQUIRED_KEYS = ("session_id", "segment", "train_indices", "chat_template_kwargs", "tools", "messages")
# 원본 Qwen/Qwen3.8-27B chat_template.jinja = 번들 GGUF tokenizer.chat_template (2026-09-17 대조)
EXPECTED_TEMPLATE_SHA256 = "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041"

Render = Callable[[list, dict, bool], str]
Encode = Callable[[str], list]


@dataclass
class Sequence:
    session_id: str
    segment: int
    kind: str  # "shared" | "separate"
    input_ids: list = field(default_factory=list)
    labels: list = field(default_factory=list)

    @property
    def target_tokens(self) -> int:
        return sum(1 for label in self.labels if label != IGNORE)


@dataclass
class Stats:
    samples: int = 0
    targets: int = 0
    shared_targets: int = 0
    separate_targets: int = 0
    over_length_targets: int = 0
    sequences: int = 0
    tokens: int = 0
    target_tokens: int = 0
    max_sequence_tokens: int = 0

    def add(self, other: "Stats") -> None:
        for name in self.__dataclass_fields__:
            if name == "max_sequence_tokens":
                self.max_sequence_tokens = max(self.max_sequence_tokens, other.max_sequence_tokens)
            else:
                setattr(self, name, getattr(self, name) + getattr(other, name))


class DataError(ValueError):
    pass


def load_samples(path: Path) -> list[dict]:
    samples = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        sample = json.loads(line)
        missing = [key for key in REQUIRED_KEYS if key not in sample]
        if missing:
            raise DataError(f"{path}:{number} 필드 없음 {missing} - B단계 추출기(v2) 출력이 아니다")
        messages = sample["messages"]
        for k in sample["train_indices"]:
            if not (isinstance(k, int) and 0 < k < len(messages) and messages[k].get("role") == "assistant"):
                raise DataError(f"{path}:{number} train_indices {k}가 assistant 메시지가 아니다")
        samples.append(sample)
    return samples


def split_sessions(samples: list[dict], holdout: float) -> tuple[list[dict], list[dict]]:
    """세션 id 해시 순서로 약 holdout 비율의 세션을 평가용으로 뗀다(세션이 2개 이상일 때 최소 1개)."""
    sessions = sorted({s["session_id"] for s in samples}, key=lambda sid: hashlib.sha256(sid.encode()).hexdigest())
    count = 0 if len(sessions) < 2 or holdout <= 0 else max(1, math.floor(len(sessions) * holdout + 0.5))
    held = set(sessions[:count])
    return [s for s in samples if s["session_id"] not in held], [s for s in samples if s["session_id"] in held]


def build_sequences(sample: dict, render: Render, encode: Encode, max_seq_len: int) -> tuple[list[Sequence], Stats]:
    messages = sample["messages"]
    stats = Stats(samples=1, targets=len(sample["train_indices"]))
    shared = Sequence(sample["session_id"], sample["segment"], "shared")
    separate: list[Sequence] = []
    consumed = ""  # 공유 시퀀스에 이미 토큰화해 넣은 렌더 문자열
    finished: list[Sequence] = []
    for position, k in enumerate(sorted(sample["train_indices"])):
        prefix = render(messages[:k], sample, True)
        upto = render(messages[:k + 1], sample, False)
        where = f"{sample['session_id']}#{sample['segment']} 응답 {k}"
        if not upto.startswith(prefix):
            raise DataError(f"{where}: 렌더 prefix 성질이 깨졌다 - 템플릿·데이터 불일치")
        # 응답의 끝은 구조로 정한다. 본문에 "<|im_end|>" 문자열이 인용돼 있어도 거기서 자르지 않는다(opencode 리뷰).
        if not upto.endswith(IM_END + "\n"):
            raise DataError(f"{where}: 마지막 assistant 렌더가 {IM_END}\\n으로 끝나지 않는다")
        end = len(upto) - 1
        if not prefix.startswith(consumed):
            # 다음 요청에서 앞 문맥이 달라졌다(예: preserve_thinking=false로 과거 reasoning 제거). 공유 시퀀스를
            # 끝내고 이 대상부터 새 공유 시퀀스를 시작한다.
            finished.append(shared)
            shared = Sequence(sample["session_id"], sample["segment"], "shared")
            consumed = ""
        prefix_ids = encode(prefix)
        target_ids = encode(upto[len(prefix):end])
        if len(prefix_ids) + len(target_ids) > max_seq_len:
            stats.over_length_targets += len(sample["train_indices"]) - position
            break
        gap_ids = encode(prefix[len(consumed):])
        exact = shared.input_ids + gap_ids == prefix_ids
        shared.input_ids += gap_ids + target_ids
        shared.labels += [IGNORE] * len(gap_ids) + (list(target_ids) if exact else [IGNORE] * len(target_ids))
        if exact:
            stats.shared_targets += 1
        else:
            separate.append(Sequence(sample["session_id"], sample["segment"], "separate",
                                     list(prefix_ids) + list(target_ids), [IGNORE] * len(prefix_ids) + list(target_ids)))
            stats.separate_targets += 1
        consumed = upto[:end]
    finished.append(shared)
    sequences = [seq for seq in finished if seq.target_tokens] + separate
    # 마지막 학습 대상 뒤의 문맥 토큰은 손실에 쓰이지 않으므로 계산하지 않게 잘라 낸다.
    for sequence in sequences:
        last = max(i for i, label in enumerate(sequence.labels) if label != IGNORE)
        del sequence.input_ids[last + 1:], sequence.labels[last + 1:]
    stats.sequences = len(sequences)
    stats.tokens = sum(len(s.input_ids) for s in sequences)
    stats.target_tokens = sum(s.target_tokens for s in sequences)
    stats.max_sequence_tokens = max((len(s.input_ids) for s in sequences), default=0)
    return sequences, stats


def build_all(samples: list[dict], render: Render, encode: Encode, max_seq_len: int) -> tuple[list[Sequence], Stats]:
    sequences, total = [], Stats()
    for sample in samples:
        built, stats = build_sequences(sample, render, encode, max_seq_len)
        sequences += built
        total.add(stats)
    return sequences, total


def server_tools(tools: list) -> list | None:
    """llama-server(b11010)가 템플릿에 넘기는 모양으로 도구 정의를 줄인다.

    common/chat.cpp common_chat_tools_parse_oaicompat → common_chat_tools_to_json_oaicompat은 type·function의
    name·description(없으면 "")·parameters(없으면 {})만 남긴다. Pi가 보내는 "strict": false 같은 필드는 모델에
    보이지 않는다(template_parity.py 실측, 2026-09-17).
    """
    if not tools:
        return None
    return [{"type": "function", "function": {"name": t["function"]["name"], "description": t["function"].get("description", ""),
                                              "parameters": t["function"].get("parameters", {})}} for t in tools]


def hf_functions(tokenizer, template: str) -> tuple[Render, Encode]:
    def render(messages, sample, generation):
        return tokenizer.apply_chat_template(messages, tools=server_tools(sample["tools"]), chat_template=template, tokenize=False,
                                             add_generation_prompt=generation, **sample["chat_template_kwargs"])

    def encode(text):
        return tokenizer(text, add_special_tokens=False)["input_ids"]

    return render, encode


def check_template(template_text: str, tokenizer=None) -> str:
    digest = hashlib.sha256(template_text.encode("utf-8")).hexdigest()
    if digest != EXPECTED_TEMPLATE_SHA256:
        raise DataError(f"템플릿 sha256 {digest} != 번들 GGUF {EXPECTED_TEMPLATE_SHA256}")
    if tokenizer is not None and hashlib.sha256((tokenizer.chat_template or "").encode("utf-8")).hexdigest() != digest:
        raise DataError("토크나이저 chat_template이 번들 GGUF 템플릿과 다르다 - base revision 확인")
    return digest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="train.jsonl을 학습 시퀀스로 바꿔 통계를 낸다(반출 전 점검)")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--tokenizer", required=True, help="Qwen/Qwen3.8-27B 토크나이저 폴더 또는 id")
    parser.add_argument("--template", type=Path, default=Path(__file__).with_name("qwen38_chat_template.jinja"))
    parser.add_argument("--max-seq-len", type=int, default=32768)
    parser.add_argument("--holdout", type=float, default=0.1)
    args = parser.parse_args(argv)

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)
    template = args.template.read_text(encoding="utf-8")
    check_template(template, tokenizer)
    samples = load_samples(args.data)
    train, held = split_sessions(samples, args.holdout)
    render, encode = hf_functions(tokenizer, template)
    report = {"data_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(), "max_seq_len": args.max_seq_len}
    for name, part in (("train", train), ("eval", held)):
        _, stats = build_all(part, render, encode, args.max_seq_len)
        report[name] = {"sessions": len({s["session_id"] for s in part}), **stats.__dict__}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["train"]["target_tokens"] == 0:
        print("[FAIL] 학습할 대상 토큰이 없다", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
