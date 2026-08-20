"""Pi의 `--mode json` 이벤트를 읽어 툴 왕복이 실제로 성립했는지 판정한다.

2026-08-19 외부 감사(GPT-5.6 Sol) 실측: Pi가 3회 재시도 끝에

    stopReason: error
    Connection error.

를 내고도 배치는 `EXITCODE=0`이었다. 종료 코드는 "모델이 답했다"의 증거가
아니다. 그래서 종료 코드가 아니라 **이벤트 내용**으로 판정한다.

다섯 가지를 본다.

1. `stopReason`이 error가 아닐 것 (그리고 아예 없지도 않을 것)
2. 최종 assistant 응답이 존재할 것
3. 토큰 수가 양수일 것 (0토큰은 요청이 모델에 닿지 않았다는 뜻이다)
4. 도구 호출과 그 결과가 둘 다 존재하고, 결과가 오류가 아닐 것
5. 최종 답변에 프로브 낱말이 있을 것 (스크립트가 직접 쓴 파일에서만 나올 수
   있는 낱말이라, 모델이 파일을 못 읽고 지어냈다면 나올 수 없다)

Pi의 이벤트 스키마 전체를 여기에 고정하지 않는다. 이 저장소에는 실제 GGUF를
띄운 왕복 산출물이 아직 없고, 스키마를 추측해 고정하면 그 추측과 어긋나는
정상 출력을 실패로 만든다. 대신 문서 전체를 훑어 `stopReason`/`stop_reason`,
`toolCall`/`tool_execution_start` 같은 **이름의 변형을 정규화해서** 찾는다.
낙관적으로 통과시키는 방향이 아니라, 찾지 못하면 실패하는 방향이다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

_DECODER = json.JSONDecoder()


def iter_json_documents(text: str) -> Iterator[Any]:
    """JSON Lines, 이어 붙인 JSON, 단일 문서를 모두 같은 방식으로 읽는다."""
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index] in " \t\r\n":
            index += 1
        if index >= length:
            return
        try:
            document, end = _DECODER.raw_decode(text, index)
        except ValueError:
            return
        yield document
        index = end


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _norm(name: str) -> str:
    return name.lower().replace("_", "").replace("-", "")


def _text_of(node: Any) -> str:
    """assistant 메시지 한 개에서 사람이 읽을 본문만 뽑는다."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_text_of(item) for item in node)
    if not isinstance(node, dict):
        return ""
    for key in ("content", "text", "message", "delta"):
        for actual in node:
            if _norm(actual) == key:
                collected = _text_of(node[actual])
                if collected:
                    return collected
    return ""


def _is_assistant(node: dict) -> bool:
    for key, value in node.items():
        if _norm(key) in ("role", "type", "kind", "event") and isinstance(value, str):
            if value.lower() in ("assistant", "assistant_message", "assistantmessage"):
                return True
    return False


def _labels(node: dict) -> list[str]:
    labels = []
    for key, value in node.items():
        if _norm(key) in ("type", "event", "name", "kind", "eventtype"):
            if isinstance(value, str):
                labels.append(value.lower())
    return labels


def collect(documents: list[Any]) -> dict:
    """판정에 쓰는 사실들을 이벤트 전체에서 모은다."""
    stop_reasons: list[str] = []
    assistant_texts: list[str] = []
    tokens = 0
    token_seen = False
    tool_calls: list[str] = []
    tool_results: list[str] = []
    errors: list[str] = []

    for document in documents:
        for node in _walk(document):
            for key, value in node.items():
                normalized = _norm(key)
                if normalized in ("stopreason", "finishreason") and isinstance(value, str):
                    stop_reasons.append(value)
                if "token" in normalized and isinstance(value, int) and not isinstance(value, bool):
                    token_seen = True
                    tokens += value
                if normalized == "usage" and isinstance(value, dict):
                    for inner_value in value.values():
                        if isinstance(inner_value, int) and not isinstance(inner_value, bool):
                            token_seen = True
                            tokens += inner_value
                if normalized in ("toolcall", "toolcalls", "toolname", "tooluse"):
                    tool_calls.append(key)
                if normalized in ("toolresult", "toolresults"):
                    tool_results.append(key)
                if normalized == "iserror" and value:
                    errors.append(f"isError={value!r}")
                if normalized == "error" and value:
                    errors.append(f"error={value!r}")
            for label in _labels(node):
                if "tool" in label:
                    if any(word in label for word in ("call", "use", "start", "request")):
                        tool_calls.append(label)
                    if any(word in label for word in ("result", "end", "output", "response")):
                        tool_results.append(label)
            if _is_assistant(node):
                text = _text_of(node).strip()
                if text:
                    assistant_texts.append(text)

    return {
        "stop_reasons": stop_reasons,
        "assistant_texts": assistant_texts,
        "tokens": tokens if token_seen else None,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "errors": errors,
        "final_text": assistant_texts[-1] if assistant_texts else "",
    }


def judge(text: str, probe_word: str) -> tuple[list[str], dict]:
    """(문제 목록, 사실). 문제가 비어 있을 때만 왕복이 성립한 것이다."""
    documents = list(iter_json_documents(text))
    if not documents:
        head = text.strip()[:200] or "(비어 있음)"
        return ([f"JSON 이벤트를 하나도 파싱하지 못했다 - 앞부분: {head}"], {})

    facts = collect(documents)
    problems: list[str] = []

    if not facts["stop_reasons"]:
        problems.append("stopReason이 이벤트 어디에도 없다 - 응답이 끝까지 오지 않았다")
    bad_stops = [reason for reason in facts["stop_reasons"] if "error" in reason.lower()]
    if bad_stops:
        problems.append(f"stopReason이 오류다: {', '.join(sorted(set(bad_stops)))}")

    if not facts["assistant_texts"]:
        problems.append("최종 assistant 응답이 없다")

    if facts["tokens"] is None:
        problems.append("토큰 수를 보고한 이벤트가 없다 - 요청이 모델에 닿았는지 알 수 없다")
    elif facts["tokens"] <= 0:
        problems.append(f"토큰 수가 양수가 아니다: {facts['tokens']}")

    if not facts["tool_calls"]:
        problems.append("도구 호출 이벤트가 없다 - 모델이 툴을 부르지 않았다")
    if not facts["tool_results"]:
        problems.append("도구 결과 이벤트가 없다 - 툴 결과가 모델로 돌아가지 않았다")
    if facts["errors"]:
        problems.append(f"오류를 보고한 이벤트가 있다: {'; '.join(sorted(set(facts['errors'])))}")

    if probe_word and facts["final_text"]:
        if probe_word.lower() not in facts["final_text"].lower():
            problems.append(
                f"최종 답변에 프로브 낱말 {probe_word}가 없다 - 모델이 파일을 읽지 못했다"
            )
    elif probe_word:
        problems.append(f"최종 답변이 없어 프로브 낱말 {probe_word}를 확인할 수 없다")

    return problems, facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tool_roundtrip", description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--expect", default="")
    arguments = parser.parse_args(argv)

    if not arguments.events.is_file():
        print(f"[FAIL] {arguments.events} 없음 - 왕복 산출물이 아예 남지 않았다", file=sys.stderr)
        return 1
    text = arguments.events.read_text(encoding="utf-8", errors="replace")
    problems, facts = judge(text, arguments.expect)
    if facts:
        print(
            "[info] stopReason={stop} tokens={tokens} toolCall={calls} toolResult={results}".format(
                stop=",".join(facts["stop_reasons"]) or "-",
                tokens=facts["tokens"] if facts["tokens"] is not None else "-",
                calls=len(facts["tool_calls"]),
                results=len(facts["tool_results"]),
            )
        )
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if problems:
        return 1
    print("[ok] 툴 왕복이 성립했다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
