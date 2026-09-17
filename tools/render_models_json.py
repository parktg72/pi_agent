"""포트와 alias를 config.env 하나에서만 받아 home\\agent\\models.json을 만든다.

2026-08-19 외부 감사(GPT-5.6 Sol) 실측: `config.env`의 `LLAMA_PORT`와 번들 루트
`models.json`의 `"baseUrl": "http://127.0.0.1:8080/v1"`는 서로 모르는 사이였다.
포트를 18080으로 바꾸면 readiness 폴링(`wait_model.py`)은 18080에서 통과하고
Pi는 8080으로 붙으려다 실패한다 - 그리고 그 실패도 exit 0이었다.

그래서 번들 루트 `models.json`은 **템플릿**이 됐다. 포트와 alias 자리에
`${LLAMA_PORT}`, `${MODEL_ALIAS}` 플레이스홀더를 두고(그 상태로도 유효한
JSON이라 구조를 검사할 수 있다), `start-pi.bat`과 `verify-offline.bat`이 매
실행마다 `config.env`의 값으로 렌더링해 `home\\agent\\models.json`에 원자적으로
쓴다. 값의 출처가 하나가 된다.

템플릿은 매니페스트 해시 범위 안에 그대로 남는다 - 렌더링 결과만 가변 영역인
`home\\agent\\`로 나간다. 그래서 운영자가 손으로 고칠 파일은 이제 없다.
"""
from __future__ import annotations

import argparse
import json
import string
import sys
from pathlib import Path

# 번들 내장 임베디드 배포판은 python312._pth 때문에 스크립트 디렉터리를
# sys.path에 넣지 않는다(2026-08-19 윈도우 실측: ModuleNotFoundError).
# 다른 tools 모듈과 같은 관용구로 명시한다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_parse import write_atomic

PLACEHOLDERS = ("LLAMA_PORT", "MODEL_ALIAS")


def render(template_text: str, port: str, alias: str, ctx: str | None = None) -> tuple[str, list[str]]:
    """(렌더링 결과, 문제 목록). 문제가 있으면 결과는 쓰면 안 된다.

    ctx가 주어지면 alias 모델의 contextWindow를 그 값으로 쓰고 maxTokens를 그 안으로
    줄인다. 2026-09-17 실측: config.env LLAMA_CTX=65536인데 템플릿의 contextWindow가
    32768로 고정돼 있어 Pi가 서버 창의 절반만 쓰고 있었다(stub 왕복 요청의
    max_completion_tokens=25539). 창 크기도 포트·alias처럼 config.env 하나에서 온다.
    """
    problems: list[str] = []
    if ctx is not None and not (ctx.isdigit() and int(ctx) > 0):
        return "", [f"LLAMA_CTX={ctx}는 양의 정수가 아니다"]
    try:
        body = string.Template(template_text).substitute(LLAMA_PORT=port, MODEL_ALIAS=alias)
    except KeyError as error:
        return "", [f"템플릿이 아는 값이 아닌 자리표시자를 쓴다: {error}"]
    except ValueError as error:
        return "", [f"템플릿의 자리표시자 문법이 깨졌다: {error}"]

    try:
        document = json.loads(body)
    except ValueError as error:
        return body, [f"렌더링 결과가 JSON이 아니다: {error}"]

    providers = document.get("providers")
    if not isinstance(providers, dict) or not providers:
        return body, ["providers 객체가 없다"]

    for name, provider in providers.items():
        base_url = provider.get("baseUrl", "")
        if f":{port}/" not in base_url:
            problems.append(f"제공자 {name}의 baseUrl에 포트 {port}가 들어가지 않았다: {base_url}")
        ids = [model.get("id") for model in provider.get("models", [])]
        if alias not in ids:
            problems.append(f"제공자 {name}의 모델 목록에 alias {alias}가 없다: {ids}")
        if ctx is not None:
            for model in provider.get("models", []):
                # llama-server는 alias 하나만 서빙한다. 다른 항목의 창까지 이 값으로
                # 바꾸면 그 모델에 없는 창을 Pi에 광고하게 된다.
                if model.get("id") != alias:
                    continue
                model["contextWindow"] = int(ctx)
                if not isinstance(model.get("maxTokens"), int) or model["maxTokens"] > int(ctx):
                    model["maxTokens"] = int(ctx)
    if ctx is not None:
        body = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    return body, problems


def check_model_id(document_text: str, model_id: str) -> list[str]:
    """PI_MODEL_ID가 렌더링된 문서 안에서 실제로 해석되는지 본다."""
    if "/" not in model_id:
        return [f"PI_MODEL_ID={model_id}는 <제공자>/<alias> 형식이 아니다"]
    provider_name, alias = model_id.split("/", 1)
    document = json.loads(document_text)
    provider = document.get("providers", {}).get(provider_name)
    if provider is None:
        return [
            f"PI_MODEL_ID={model_id}의 제공자 {provider_name}가 models.json에 없다 "
            f"(있는 제공자: {sorted(document.get('providers', {}))})"
        ]
    ids = [model.get("id") for model in provider.get("models", [])]
    if alias not in ids:
        return [f"PI_MODEL_ID={model_id}의 모델 {alias}가 제공자 {provider_name}에 없다: {ids}"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="render_models_json", description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--port", required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--ctx", required=True)
    arguments = parser.parse_args(argv)

    if not arguments.template.is_file():
        print(
            f"[FAIL] {arguments.template} 없음 - Pi가 로컬 엔드포인트를 인식할 방법이 없다",
            file=sys.stderr,
        )
        return 1
    template_text = arguments.template.read_text(encoding="utf-8")

    body, problems = render(template_text, arguments.port, arguments.alias, arguments.ctx)
    if not problems and arguments.model_id:
        problems = check_model_id(body, arguments.model_id)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if problems:
        return 1

    try:
        write_atomic(arguments.out, body)
    except OSError as error:
        print(f"[FAIL] {arguments.out}를 쓰지 못했다: {error}", file=sys.stderr)
        return 1
    print(f"[ok] models.json 생성: 포트 {arguments.port}, alias {arguments.alias}, contextWindow {arguments.ctx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
