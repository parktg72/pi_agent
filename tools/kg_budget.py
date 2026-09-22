"""LightRAG가 실제로 쓸 요청 예산이 LLM 서버 슬롯 안에 드는지 확인한다.

start-lightrag.bat이 LightRAG를 띄우기 직전에 부른다(codex R5 #3). 보존된
home\\kg\\work\\.env를 운영자가 고쳤을 수 있으므로 템플릿이 아니라 **적용될 값**을 본다:
LightRAG는 .env를 override=False로 읽으므로(lightrag/api/config.py) 프로세스 환경변수가
같은 키의 .env 값을 이긴다. 키가 없으면 LightRAG 1.5.7 기본값을 쓴다.

요청마다 입력 + 출력 상한이 슬롯의 85% 이하여야 한다. LightRAG는 tiktoken으로 세고
모델은 Qwen3.8 토크나이저로 세서 둘이 다르다.
- 첫 추출: 시스템 프롬프트(예시 포함) + 사용자 템플릿 + CHUNK_SIZE + 출력. 1.5.7은 이 요청에
  상한을 걸지 않는다. 시스템 프롬프트는 스테이징 PC에서 Qwen3.8 토크나이저로 잰 1,551(text)/
  1,477(json) 토큰, tiktoken 1,497/1,410(tasks/pi-agent-kg-align/artifacts/measure_extract.py).
- gleaning: MAX_EXTRACT_INPUT_TOKENS + 출력(넘으면 LightRAG가 gleaning을 건너뛴다).
- 설명 요약: SUMMARY_CONTEXT_SIZE + 출력.
- 질의: MAX_TOTAL_TOKENS + 출력, 그리고 MAX_ENTITY_TOKENS + MAX_RELATION_TOKENS < MAX_TOTAL_TOKENS.
출력 상한(OPENAI_LLM_MAX_TOKENS)이 없으면 출력이 슬롯 끝까지 갈 수 있어 거부한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Mapping

MARGIN = 0.85
MEASURED_EXTRACT_SYSTEM_TOKENS = 1600
USER_TEMPLATE_TOKENS = 250
# lightrag-hku 1.5.7 기본값(키가 없을 때). 출력 상한은 기본이 없다.
LIGHTRAG_DEFAULTS = {
    "CHUNK_SIZE": 1200,
    "MAX_EXTRACT_INPUT_TOKENS": 20480,
    "SUMMARY_CONTEXT_SIZE": 12000,
    "MAX_TOTAL_TOKENS": 30000,
    "MAX_ENTITY_TOKENS": 6000,
    "MAX_RELATION_TOKENS": 8000,
}
KEYS = ("OPENAI_LLM_MAX_TOKENS", *LIGHTRAG_DEFAULTS)


def parse_env_file(text: str) -> dict[str, str]:
    """python-dotenv가 없을 때의 대체 파서(테스트·부트스트랩용). `export ` 접두어와 따옴표를 처리한다.

    LightRAG와 같은 결과를 내려면 read_env_file()이 python-dotenv(dotenv_values)를 먼저 쓴다 -
    KG venv에는 LightRAG 의존성으로 설치돼 있다(codex R6 #1).
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def read_env_file(path: Path) -> dict[str, str]:
    """LightRAG와 같은 파서로 .env를 읽는다: python-dotenv가 있으면 dotenv_values(변수 확장·export 포함)."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return parse_env_file(path.read_text(encoding="utf-8"))
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def effective(env_file: Mapping[str, str], process: Mapping[str, str]) -> dict[str, str]:
    merged = dict(env_file)
    for key in KEYS:
        if key in process:
            merged[key] = process[key]
    return merged


def check_budget(env: Mapping[str, str], slot: int) -> list[str]:
    problems: list[str] = []
    ceiling = int(slot * MARGIN)

    def number(key: str) -> int | None:
        raw = env.get(key, "")
        if raw == "":
            return LIGHTRAG_DEFAULTS.get(key)
        try:
            value = int(raw)
        except ValueError:
            problems.append(f"{key}={raw!r}가 정수가 아니다")
            return None
        # 0이나 음수는 LightRAG에서 "제한 없음"이 되기도 한다(MAX_EXTRACT_INPUT_TOKENS=0이면
        # gleaning 상한 검사를 건너뛴다 - operate.py `max_extract_input_tokens > 0`). 양수만 받는다.
        if value <= 0:
            problems.append(f"{key}={value}은 양수여야 한다 - 0 이하는 상한을 없애거나 요청을 깨뜨린다")
            return None
        return value

    out = number("OPENAI_LLM_MAX_TOKENS")
    if out is None:
        if "OPENAI_LLM_MAX_TOKENS" not in env or env.get("OPENAI_LLM_MAX_TOKENS", "") == "":
            problems.append("OPENAI_LLM_MAX_TOKENS가 없다 - 출력이 슬롯 끝까지 갈 수 있다")
        return problems
    requests = {
        "첫 추출(시스템+템플릿+CHUNK_SIZE)": (
            MEASURED_EXTRACT_SYSTEM_TOKENS + USER_TEMPLATE_TOKENS + (number("CHUNK_SIZE") or 0)
        ),
        "gleaning(MAX_EXTRACT_INPUT_TOKENS)": number("MAX_EXTRACT_INPUT_TOKENS"),
        "설명 요약(SUMMARY_CONTEXT_SIZE)": number("SUMMARY_CONTEXT_SIZE"),
        "질의(MAX_TOTAL_TOKENS)": number("MAX_TOTAL_TOKENS"),
    }
    for name, value in requests.items():
        if value is None:
            continue
        if value + out > ceiling:
            problems.append(
                f"{name} {value} + 출력 {out} = {value + out}이 슬롯 {slot}의 {int(MARGIN * 100)}%({ceiling})를 넘는다"
            )
    entity, relation, total = number("MAX_ENTITY_TOKENS"), number("MAX_RELATION_TOKENS"), number("MAX_TOTAL_TOKENS")
    if None not in (entity, relation, total) and entity + relation >= total:  # type: ignore[operator]
        problems.append(f"MAX_ENTITY_TOKENS + MAX_RELATION_TOKENS({entity + relation})가 MAX_TOTAL_TOKENS({total}) 이상이다")  # type: ignore[operator]
    return problems


def main(argv: list[str], fetch: Callable[[str], dict] | None = None, process: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kg_budget")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args(argv)

    def default_fetch(url: str) -> dict:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        env_file = read_env_file(args.env_file)
    except OSError as error:
        print(f"[FAIL] {args.env_file}를 읽지 못했다 - {error}", file=sys.stderr)
        return 1
    try:
        props = (fetch or default_fetch)(f"{args.base_url}/props")
        slot = props["default_generation_settings"]["n_ctx"]
        if not isinstance(slot, int):
            raise TypeError("n_ctx가 정수가 아니다")
    except Exception as error:  # 서버가 없거나 응답이 깨졌다
        print(f"[FAIL] {args.base_url}/props에서 슬롯 창을 읽지 못했다 - {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    problems = check_budget(effective(env_file, os.environ if process is None else process), slot)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if problems:
        print(f"[FAIL] {args.env_file}의 값을 슬롯 {slot}에 맞게 낮추거나 KG_CTX / KG_PARALLEL을 바꿔라", file=sys.stderr)
        return 1
    print(f"[ok] LightRAG 요청 예산이 슬롯 {slot} 안에 든다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
