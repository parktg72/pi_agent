"""config.env를 CMD 코드로 실행하지 않고 파싱한다.

2026-08-19 외부 감사(GPT-5.6 Sol) 실측: `config.env`를 `home\\agent\\config.cmd`로
복사해 `call`하면 그 파일은 **설정이 아니라 코드**가 된다.

- `&`가 든 값은 `&` 뒤가 별도 명령으로 실행된다.
- `%VAR%`는 값에서 소실된다(해당 변수가 없으면 빈 문자열로 치환).
- `!VAR!`는 지연 확장 구간에서 소실된다.

신뢰된 설정 파일이라도 경로·alias가 **조용히 변형**되는 것이 문제다. 변형된
alias는 `/v1/models`에 없는 모델을 요청하게 만들고, 그 실패는 지금까지
exit 0으로 보고돼 왔다.

그래서 여기서 한다:

1. ASCII만 받는다. 비ASCII 바이트가 있으면 `call`되는 `.cmd`에서 cmd.exe의
   줄 오프셋 계산이 어긋난다(2026-08-18 실측). 파일에 비ASCII가 없으면 그
   문제 자체가 성립하지 않는다.
2. 허용 키 목록 밖의 키를 거부한다. 오타는 조용히 무시되는 대신 멈춘다.
3. CMD 메타문자(`& | < > ^ % ! "`)가 값에 나타나면 거부한다.
4. 키별 타입을 검사한다(포트 범위, 정수, 백엔드 이름, `<제공자>/<alias>` 형식).
5. 검증을 통과한 값만 `set "K=V"` 문으로 이뤄진 sanitized `.cmd`로 원자적으로
   쓴다. 그 파일에는 검증된 값 외에는 아무 코드도 없다.

`.bat`은 그 sanitized 사본만 `call`한다. 파싱이 실패하면 nonzero로 끝나고
`.bat`은 거기서 멈춘다.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# 번들 내장 임베디드 파이썬은 스크립트 디렉터리를 sys.path에 넣지 않는다
# (render_models_json.py와 같은 관용구).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from manifest import EXCLUDED_PATHS

# cmd.exe가 값을 코드로 해석하게 만드는 문자들. 큰따옴표는 `set "K=V"`의
# 인용 자체를 깨뜨리므로 같이 막는다.
FORBIDDEN_VALUE_CHARS = '&|<>^%!"'

_SET_QUOTED = re.compile(r'^set\s+"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)"$')
_SET_BARE = re.compile(r'^set\s+(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$')

BACKENDS = ("cuda", "vulkan", "cpu")
# models.json의 thinkingLevelMap이 null이 아닌 값을 준 단계만 받는다. Pi는
# 지원하지 않는 단계를 조용히 가까운 단계로 당겨 쓰므로(clampThinkingLevel),
# 여기서 걸러야 운영자가 적은 값과 실제로 도는 값이 어긋나지 않는다.
THINKING_LEVELS = ("off", "low", "medium", "high")


def _check_port(value: str) -> str | None:
    if not value.isdigit():
        return "정수가 아니다"
    number = int(value)
    if not (1 <= number <= 65535):
        return "1~65535 범위 밖이다"
    return None


def _check_positive_int(value: str) -> str | None:
    if not value.isdigit():
        return "정수가 아니다"
    if int(value) <= 0:
        return "0보다 커야 한다"
    return None


def _check_backend(value: str) -> str | None:
    if value.lower() not in BACKENDS:
        return f"{' | '.join(BACKENDS)} 중 하나여야 한다"
    return None


def _check_flag(value: str) -> str | None:
    if value not in ("0", "1"):
        return "0 또는 1이어야 한다"
    return None


def _check_model_id(value: str) -> str | None:
    if value.count("/") != 1:
        return "<제공자>/<MODEL_ALIAS> 형식이어야 한다"
    provider, alias = value.split("/", 1)
    if not provider or not alias:
        return "<제공자>/<MODEL_ALIAS> 형식이어야 한다"
    return None


def _check_filename(value: str) -> str | None:
    if ".." in value:
        return "상위 디렉터리 참조(..)는 쓸 수 없다"
    # 매니페스트가 해시하지 않는 모델(스테이징 PC에만 있는 것)은 고를 수 없다.
    # 반입 매체에 함께 복사돼도 전송 손상을 검사받지 않은 파일이다(2026-09-17 agy 리뷰).
    relative = "models/" + value.replace("\\", "/").lstrip("/")
    for excluded in EXCLUDED_PATHS:
        if relative == excluded or relative.startswith(excluded + "/"):
            return f"{excluded}는 반입 대상이 아니라 매니페스트가 검사하지 않는다 - 반입 모델(Q6_K·Q4_K_M)을 쓴다"
    return None


def _check_thinking(value: str) -> str | None:
    if value.lower() not in THINKING_LEVELS:
        return f"{' | '.join(THINKING_LEVELS)} 중 하나여야 한다"
    return None


def _check_tensor_split(value: str) -> str | None:
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?(,[0-9]+(\.[0-9]+)?)*", value):
        return "쉼표로 구분한 숫자여야 한다(예: 1,1.2,1.2)"
    return None


# KV 캐시 타입. q8_0은 VRAM이 빠듯한 양자화(Q6_K 등)에서 쓰고, 그보다 낮은
# 비트는 품질 손실 대비 이득이 작아 받지 않는다. 양자화 KV는 flash-attn을
# 요구하는데 start-llama.bat이 -fa on을 고정한다(b11010 fattn.cu: Pascal은
# tile/vec 커널로 동작).
KV_TYPES = ("f16", "q8_0")


def _check_kv_type(value: str) -> str | None:
    if value not in KV_TYPES:
        return f"{' | '.join(KV_TYPES)} 중 하나여야 한다"
    return None


def _check_lora_file(value: str) -> str | None:
    # llama-server --lora-scaled는 FNAME:SCALE을 ':'로, 여러 개를 ','로 나눈다
    # (b11010 common/arg.cpp). 그 둘이 이름에 있으면 기동이 실패하거나 다른
    # 파일을 연다. lora\ 바로 아래의 파일 이름만 받는다.
    # 괄호도 막는다: start-llama.bat의 if ( ... ) 블록 안 echo에서 값이 펼쳐질 때
    # ')'가 블록을 조기에 닫는다(2026-09-17 opencode 리뷰). 그래서 금지 목록이 아니라
    # 허용 문자 집합으로 좁힌다.
    if ".." in value or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        return "lora\\ 바로 아래의 파일 이름만 쓴다(영문·숫자·._- 만, 경로 구분자·:·,·괄호 불가)"
    if not value.lower().endswith(".gguf"):
        return "GGUF 어댑터(.gguf)여야 한다 - PEFT 원본은 convert_lora_to_gguf.py로 변환한다"
    return None


def _check_lora_scale(value: str) -> str | None:
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", value):
        return "0보다 큰 숫자여야 한다(예: 1.0)"
    if not (0 < float(value) <= 2):
        return "0 초과 2 이하여야 한다 - 학습 배율(1.0)에서 크게 벗어난 값은 오타일 가능성이 높다"
    return None


# 허용 키와 키별 검사. 여기 없는 키는 거부한다 - 오타가 조용히 무시되는 대신
# 멈춘다. .bat 어느 곳도 읽지 않는 키를 config.env에 적어 두면 그것을 설정한
# 줄 알고 지나가게 되기 때문이다.
ALLOWED_KEYS: dict[str, object] = {
    "LLAMA_BACKEND": _check_backend,
    "LLAMA_PORT": _check_port,
    "LLAMA_CTX": _check_positive_int,
    "MODEL_FILE": _check_filename,
    "MODEL_ALIAS": None,
    "GPU_TENSOR_SPLIT": _check_tensor_split,
    "MMPROJ_FILE": _check_filename,
    "PI_MODEL_ID": _check_model_id,
    "PI_PROVIDER": None,
    # Qwen3.8의 채팅 템플릿은 reasoning_effort를 안 주면 xhigh로 사고한다
    # (GGUF의 tokenizer.chat_template 실측: reasoning_effort|default('xhigh')).
    # 32768 창에서 그 기본값은 답이 잘리는 쪽으로 기운다. start-pi.bat이
    # 이 값을 --thinking으로 넘기고, 비어 있으면 medium을 쓴다.
    "PI_THINKING": _check_thinking,
    "MODEL_LOAD_TIMEOUT": _check_positive_int,
    "PYTHON_CMD": None,
    # 16.8GB 모델을 CPU로 올리는 것은 사고로 선택될 일이 아니다. 진단 목적일
    # 때만 1로 둔다(start-llama.bat이 이 값을 요구한다).
    "ALLOW_CPU_DIAGNOSTIC": _check_flag,
    # 2026-09-17 설정 최적화(1080 Ti x3, RAM 128GB). 근거: tasks 합의 문서와
    # win\\config.env.example의 각 항목 설명.
    "LLAMA_KV_TYPE": _check_kv_type,
    "LLAMA_CACHE_RAM_MIB": _check_positive_int,
    "LLAMA_SPEC_MTP": _check_flag,
    # 대상 PC에서 학습한 LoRA 어댑터. 비우면 기본 모델만 뜬다(롤백 = 비우기).
    "LORA_FILE": _check_lora_file,
    "LORA_SCALE": _check_lora_scale,
}


def parse_text(text: str) -> tuple[dict[str, str], list[str]]:
    """(값, 문제 목록). 문제가 하나라도 있으면 호출자는 실패로 다뤄야 한다."""
    values: dict[str, str] = {}
    problems: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("rem ") or lowered == "rem" or line.startswith("::"):
            continue
        if lowered in ("@echo off", "echo off", "@echo on"):
            continue
        match = _SET_QUOTED.match(line) or _SET_BARE.match(line)
        if not match:
            problems.append(f"{number}행: set 문도 주석도 아니다 - {line!r}")
            continue
        key = match.group("key").upper()
        value = match.group("value")
        if key not in ALLOWED_KEYS:
            problems.append(f"{number}행: 허용되지 않은 키 {key} - .bat이 읽지 않는 이름이다")
            continue
        bad = [character for character in value if character in FORBIDDEN_VALUE_CHARS]
        if bad:
            problems.append(
                f"{number}행: {key}의 값에 CMD 메타문자 {''.join(sorted(set(bad)))} 가 있다 - "
                "cmd.exe가 값을 코드로 해석한다"
            )
            continue
        if any(character < " " or character > "~" for character in value):
            problems.append(f"{number}행: {key}의 값에 출력 가능한 ASCII 밖의 문자가 있다")
            continue
        if value:
            check = ALLOWED_KEYS[key]
            if check is not None:
                reason = check(value)  # type: ignore[operator]
                if reason:
                    problems.append(f"{number}행: {key}={value} - {reason}")
                    continue
        if key in values:
            problems.append(f"{number}행: {key}가 두 번 설정됐다 - 어느 값이 쓰일지 읽는 사람이 알 수 없다")
            continue
        values[key] = value

    alias = values.get("MODEL_ALIAS", "")
    model_id = values.get("PI_MODEL_ID", "")
    if alias and model_id and "/" in model_id:
        if model_id.split("/", 1)[1] != alias:
            problems.append(
                f"PI_MODEL_ID={model_id}의 뒷부분이 MODEL_ALIAS={alias}와 글자 그대로 같지 않다 - "
                "Pi가 llama-server에 없는 모델 ID를 요청하게 된다"
            )
    return values, problems


def render_cmd(values: dict[str, str]) -> str:
    """검증된 값만 담은 sanitized .cmd 본문. 여기에는 set 문 외에 코드가 없다."""
    lines = [
        "@echo off",
        "rem Generated by tools/config_parse.py from config.env - do not edit.",
        "rem Every value below passed the allowed-key and character checks.",
    ]
    for key in sorted(values):
        lines.append(f'set "{key}={values[key]}"')
    return "\r\n".join(lines) + "\r\n"


def write_atomic(path: Path, body: str) -> None:
    """같은 디렉터리에 임시 파일로 쓰고 os.replace로 바꾼다.

    쓰는 도중에 죽어도 반쯤 쓰인 .cmd가 call되지 않는다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(body, encoding="ascii", newline="")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="config_parse", description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    arguments = parser.parse_args(argv)

    if not arguments.config.is_file():
        print(f"[FAIL] {arguments.config} 없음", file=sys.stderr)
        return 1
    raw = arguments.config.read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        print(
            f"[FAIL] {arguments.config}에 비ASCII 바이트가 있다(오프셋 {error.start}) - "
            "cmd.exe가 줄 오프셋을 잘못 계산해 줄 중간부터 실행한다. 값은 ASCII로만 적어라.",
            file=sys.stderr,
        )
        return 1

    values, problems = parse_text(text)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if problems:
        print(f"[FAIL] {arguments.config}를 받아들이지 않았다 - 위 문제를 고쳐라", file=sys.stderr)
        return 1

    try:
        write_atomic(arguments.out, render_cmd(values))
    except OSError as error:
        print(f"[FAIL] {arguments.out}를 쓰지 못했다: {error}", file=sys.stderr)
        return 1
    print(f"[ok] config.env에서 {len(values)}개 값을 읽었다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
