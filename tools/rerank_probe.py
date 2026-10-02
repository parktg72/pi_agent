"""LightRAG가 실제로 쓸 리랭커 설정으로 리랭커 서버가 답하는지 확인한다.

start-lightrag.bat이 LightRAG를 띄우기 직전에 부른다(tasks/pi-agent-reranker 합의 7·8).
LightRAG 1.5.7은 rerank 호출이 실패해도 오류 로그만 남기고 원래 청크 순서로 질의를 계속한다
(lightrag/utils.py) - 질의가 성공했다는 것만으로는 리랭커가 붙었는지 알 수 없다. 그래서
켜져 있으면 여기서 실제 요청을 한 번 보내 보고, 답이 틀리면 기동을 거부한다.

kg_budget.py와 같은 규칙으로 **적용될 값**을 본다: 보존된 home\\kg\\work\\.env를 DotEnv
(override=False)로 읽고, 같은 키의 프로세스 환경변수가 이긴다.

- LightRAG의 PORT는 리랭커가 꺼져 있어도 LLM·임베딩 서버 포트와 달라야 한다.
- RERANK_BINDING은 null(끔) 또는 cohere만 받는다. jina·aliyun은 요청·응답 모양이 달라
  이 번들에서 확인한 적이 없다.
- cohere면 LightRAG가 보낼 URL·model·key로 문서 2개, top_n=2를 보낸다. llama-server의
  점수는 정규화되지 않은 값일 수 있어 범위는 보지 않는다(음수·1 초과 허용).
- 프록시를 쓰지 않는다. LightRAG의 rerank 호출(aiohttp, trust_env=False)은 프록시 설정을
  보지 않는데 urllib은 본다 - 그대로 두면 리랭커가 멀쩡해도 프록시 때문에 거부할 수 있다.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

# 스크립트 디렉터리가 sys.path에 없는 파이썬에서도 돌게 한다(config_parse.py와 같은 관용구).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kg_budget import read_env_file

KEYS = ("PORT", "RERANK_BINDING", "RERANK_BINDING_HOST", "RERANK_MODEL", "RERANK_BINDING_API_KEY", "COHERE_API_KEY")
# lightrag-hku 1.5.7 기본값(키가 없을 때).
LIGHTRAG_PORT = "9621"
COHERE_MODEL = "rerank-v3.5"
PROBE_TIMEOUT = 10
QUERY = "What is a panda?"
DOCUMENTS = ["The giant panda is a bear species endemic to China.", "A list of port numbers."]
HOW_TO_DISABLE = "리랭커 없이 쓰려면 .env에 RERANK_BINDING=null 과 RERANK_BY_DEFAULT=false 를 둔다"


def effective(env_file: Mapping[str, str], process: Mapping[str, str]) -> dict[str, str]:
    merged = dict(env_file)
    for key in KEYS:
        if key in process:
            merged[key] = process[key]
    return merged


def check_ports(env: Mapping[str, str], servers: Mapping[str, int]) -> list[str]:
    raw = env.get("PORT") or LIGHTRAG_PORT
    if not raw.isdigit():
        return [f"LightRAG PORT={raw}가 정수가 아니다"]
    return [
        f"LightRAG PORT={int(raw)}가 {name}와 같다 - 두 서버가 한 포트를 두고 다툰다"
        for name, port in servers.items()
        if port == int(raw)
    ]


def check_response(body: object) -> str | None:
    """보낸 문서 2개에 대한 답인지 본다. 문제가 없으면 None."""
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list) or len(results) != len(DOCUMENTS):
        return f"results가 문서 수({len(DOCUMENTS)})만큼의 목록이 아니다"
    seen = set()
    for item in results:
        if not isinstance(item, dict):
            return "results 항목이 객체가 아니다"
        index, score = item.get("index"), item.get("relevance_score")
        if isinstance(index, bool) or not isinstance(index, int) or not (0 <= index < len(DOCUMENTS)):
            return f"index={index!r}가 보낸 문서 번호가 아니다"
        if index in seen:
            return f"index={index}가 두 번 나왔다"
        seen.add(index)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            return f"relevance_score={score!r}가 유한한 수가 아니다"
    return None


def default_post(url: str, payload: dict, api_key: str | None) -> object:
    headers = {"Content-Type": "application/json"}
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=PROBE_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def main(
    argv: list[str],
    post: Callable[[str, dict, str | None], object] | None = None,
    process: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="rerank_probe")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--llama-port", required=True, type=int)
    parser.add_argument("--embed-port", required=True, type=int)
    args = parser.parse_args(argv)

    try:
        env_file = read_env_file(args.env_file)
    except OSError as error:
        print(f"[FAIL] {args.env_file}를 읽지 못했다 - {error}", file=sys.stderr)
        return 1
    env = effective(env_file, os.environ if process is None else process)
    servers = {"LLAMA_PORT": args.llama_port, "EMBED_PORT": args.embed_port}
    # 키가 없을 때만 LightRAG 기본값 null이다. 빈 값은 LightRAG가 그대로 받아 기동에 실패한다.
    binding = env.get("RERANK_BINDING", "null")
    url = env.get("RERANK_BINDING_HOST", "")
    if binding == "cohere" and url:
        try:
            port = urlsplit(url).port
        except ValueError:
            port = None
        if port is not None:
            servers["RERANK_BINDING_HOST의 포트"] = port

    problems = check_ports(env, servers)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if problems:
        return 1
    if binding == "null":
        print("[info] RERANK_BINDING=null - 리랭커 없이 뜬다(질의는 원래 청크 순서를 쓴다)")
        return 0
    if binding != "cohere":
        print(
            f"[FAIL] RERANK_BINDING={binding} - 이 번들은 cohere(번들 llama-server의 /v1/rerank) 또는 "
            "null만 받는다. 다른 바인딩은 요청·응답 모양이 달라 확인한 적이 없다",
            file=sys.stderr,
        )
        return 1
    if not url:
        print(
            "[FAIL] RERANK_BINDING_HOST가 없다 - 비우면 LightRAG가 외부 Cohere 주소로 나가려 한다. "
            "start-lightrag.bat으로 띄우거나 로컬 주소를 적어라",
            file=sys.stderr,
        )
        return 1
    # LightRAG와 같은 값: 모델은 키가 없을 때만 바인딩 기본값(빈 값은 그대로 보낸다), 키는
    # RERANK_BINDING_API_KEY가 없으면 COHERE_API_KEY(lightrag/rerank.py cohere_rerank).
    api_key = env.get("RERANK_BINDING_API_KEY")
    if api_key is None:
        api_key = env.get("COHERE_API_KEY") or None
    payload = {
        "model": env.get("RERANK_MODEL", COHERE_MODEL),
        "query": QUERY,
        "documents": DOCUMENTS,
        "top_n": len(DOCUMENTS),
    }
    try:
        body = (post or default_post)(url, payload, api_key)
    except Exception as error:  # 서버가 없거나 리랭커로 뜨지 않았다
        print(f"[FAIL] {url}가 답하지 않았다 - {type(error).__name__}: {error}", file=sys.stderr)
        print(f"[FAIL] start-rerank.bat을 먼저 띄워라. {HOW_TO_DISABLE}", file=sys.stderr)
        return 1
    reason = check_response(body)
    if reason:
        print(f"[FAIL] {url}의 답이 리랭커 답이 아니다 - {reason}", file=sys.stderr)
        print(f"[FAIL] start-rerank.bat으로 띄운 서버인지 확인하라. {HOW_TO_DISABLE}", file=sys.stderr)
        return 1
    print(f"[ok] 리랭커가 {url}에서 답한다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
