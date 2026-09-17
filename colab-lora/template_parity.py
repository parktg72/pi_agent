"""학습 렌더(HF jinja2)와 추론 렌더(llama-server minja)가 같은지 대조한다 (C단계 합의 15).

train.jsonl의 학습 대상 응답 k마다 Pi가 보내는 모양의 요청(messages[:k], tools, chat_template_kwargs,
도구 인자는 JSON 문자열)을 llama-server `/apply-template`에 보내고, `/tokenize`로 토큰 ID를 받아
HF `apply_chat_template`(인자 dict)·HF 토크나이저 결과와 비교한다. 대상 응답 조각의 토큰화도 비교한다.

llama-server에는 번들과 같은 토크나이저·템플릿이 든 GGUF면 무엇이든 된다(가중치 무관) — 예: 원본 설정을
줄인 초소형 GGUF(artifacts/c-probe)의 tokenizer.* 메타데이터는 번들 Q6_K와 같다.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dataset  # noqa: E402


def post(server: str, path: str, body: dict) -> dict:
    request = urllib.request.Request(server.rstrip("/") + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def as_pi_request(messages: list) -> list:
    """Pi openai-completions 직렬화처럼 도구 인자를 JSON.stringify 문자열로 되돌린다."""
    out = copy.deepcopy(messages)
    for message in out:
        for call in message.get("tool_calls") or []:
            call["function"]["arguments"] = json.dumps(call["function"]["arguments"], ensure_ascii=False, separators=(",", ":"))
    return out


def first_difference(a, b) -> int:
    return next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--server", required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--template", type=Path, default=Path(__file__).with_name("qwen38_chat_template.jinja"))
    args = p.parse_args(argv)

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)
    template = args.template.read_text(encoding="utf-8")
    dataset.check_template(template, tokenizer)
    render, encode = dataset.hf_functions(tokenizer, template)
    checked, failures = 0, []
    for sample in dataset.load_samples(args.data):
        for k in sample["train_indices"]:
            label = f"{sample['session_id']}#{sample['segment']} k={k}"
            expected = render(sample["messages"][:k], sample, True)
            body = {"messages": as_pi_request(sample["messages"][:k]), "tools": sample["tools"],
                    "chat_template_kwargs": sample["chat_template_kwargs"]}
            prompt = post(args.server, "/apply-template", body)["prompt"]
            if prompt != expected:
                at = first_difference(prompt, expected)
                failures.append({"where": label, "kind": "template", "at": at, "server": prompt[at - 60:at + 80], "hf": expected[at - 60:at + 80]})
                continue
            server_ids = post(args.server, "/tokenize", {"content": prompt, "add_special": False, "parse_special": True})["tokens"]
            if server_ids != encode(prompt):
                at = first_difference(server_ids, encode(prompt))
                failures.append({"where": label, "kind": "tokens", "at": at, "server": server_ids[at:at + 8], "hf": encode(prompt)[at:at + 8]})
                continue
            upto = render(sample["messages"][:k + 1], sample, False)
            target = upto[len(expected):upto.index(dataset.IM_END, len(expected)) + len(dataset.IM_END)]
            if post(args.server, "/tokenize", {"content": target, "add_special": False, "parse_special": True})["tokens"] != encode(target):
                failures.append({"where": label, "kind": "target tokens"})
                continue
            checked += 1
    print(json.dumps({"checked_targets": checked, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures or not checked else 0


if __name__ == "__main__":
    raise SystemExit(main())
