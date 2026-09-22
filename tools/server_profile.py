"""Pi를 붙이기 전에 llama-server가 Pi용 구성으로 떠 있는지 확인한다.

같은 포트(LLAMA_PORT)에 `start-llama.bat kg`(LightRAG 엔티티 추출, 기본 4슬롯 x 8192)이
떠 있으면 Pi의 기본 요청(약 13k 토큰)이 슬롯 창을 넘어 첫 턴부터 깨진다. 문서 안내로는
막을 수 없어서 기동 전에 코드로 거부한다(tasks/pi-agent-kg-align 합의 13).

b11010 `GET /props`(tools/server/server-context.cpp get_res_props)가 주는 값을 본다:
- `total_slots` = `--parallel`
- `default_generation_settings.n_ctx` = 슬롯당 창
- `chat_template` = 서버가 실제로 쓰는 템플릿 원문

조회 실패·필드 누락·값 불일치는 모두 거부다. 확인할 수 없는 서버에 Pi를 붙이지 않는다.

LightRAG 쪽 반대 방향 검사(슬롯이 요청 예산보다 큰가)는 tools/kg_budget.py가 한다.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Callable


def _normalize(text: str) -> str:
    # 체크아웃·복사 과정의 줄바꿈 차이만 흡수한다. 그 밖의 차이는 다른 템플릿이다.
    return text.replace("\r\n", "\n").rstrip("\n")


def check_props(props: dict, expected_ctx: int, template: str | None) -> list[str]:
    problems: list[str] = []
    slots = props.get("total_slots")
    settings = props.get("default_generation_settings")
    n_ctx = settings.get("n_ctx") if isinstance(settings, dict) else None
    if not isinstance(slots, int):
        problems.append("/props에 total_slots가 없다 - 서버 구성을 확인할 수 없다")
    elif slots != 1:
        problems.append(
            f"서버 슬롯이 {slots}개다 - start-llama.bat kg(LightRAG 추출) 구성으로 보인다. "
            "Pi는 슬롯 1개 서버에만 붙인다: 그 창을 닫고 인자 없이 start-llama.bat을 다시 띄워라"
        )
    if not isinstance(n_ctx, int):
        problems.append("/props에 default_generation_settings.n_ctx가 없다 - 슬롯 창을 확인할 수 없다")
    elif n_ctx != expected_ctx:
        problems.append(
            f"서버 슬롯 창 {n_ctx}이 LLAMA_CTX {expected_ctx}과 다르다 - Pi는 LLAMA_CTX로 압축 시점을 잡으므로 "
            "창이 다르면 요청이 넘치거나 압축이 어긋난다"
        )
    if template is not None:
        served = props.get("chat_template")
        if not isinstance(served, str):
            problems.append("/props에 chat_template이 없다 - 고정한 템플릿이 적용됐는지 확인할 수 없다")
        elif _normalize(served) != _normalize(template):
            problems.append(
                "서버가 쓰는 채팅 템플릿이 CHAT_TEMPLATE_FILE과 다르다 - start-llama.bat이 이 config.env로 "
                "뜬 서버인지 확인하라"
            )
    return problems


def main(argv: list[str], fetch: Callable[[str], dict] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="server_profile")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ctx", required=True, type=int, help="슬롯 1개, 슬롯 창 == 이 값")
    parser.add_argument("--template-file", type=Path, default=None)
    args = parser.parse_args(argv)

    def default_fetch(url: str) -> dict:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    template = None
    if args.template_file is not None:
        try:
            template = args.template_file.read_text(encoding="utf-8")
        except OSError as error:
            print(f"[FAIL] 템플릿 파일을 읽지 못했다: {args.template_file} - {error}", file=sys.stderr)
            return 1
    try:
        props = (fetch or default_fetch)(f"{args.base_url}/props")
    except Exception as error:  # 서버가 없거나 응답이 깨졌다
        print(f"[FAIL] {args.base_url}/props 조회 실패 - {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    if not isinstance(props, dict):
        print("[FAIL] /props 응답이 JSON 객체가 아니다", file=sys.stderr)
        return 1
    problems = check_props(props, args.ctx, template)
    done = f"[ok] 서버 구성: 슬롯 1개, 창 {args.ctx}" + (", 고정 템플릿 일치" if template is not None else "")
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if problems:
        return 1
    print(done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
