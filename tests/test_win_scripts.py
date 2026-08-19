import re
from pathlib import Path

WIN = Path(__file__).resolve().parents[1] / "win"


# cmd.exe는 UTF-8(코드페이지 65001) 배치 파일을 읽을 때 줄을 바이트 오프셋으로
# 다시 찾는다. 비ASCII 문자가 있으면 그 계산이 어긋나 줄 중간부터 명령으로
# 실행된다. 2026-08-18 윈도우 실측: UTF-8/CRLF config.env를 call하면
# "'?워'은(는) 내부 또는 외부 명령이 아닙니다" 류 오류가 6건 났고, 같은 내용을
# CP949로 인코딩하면 한 건도 나지 않았다. 그래서 한때는 이 번들의 .bat과 config
# 계열을 CP949로 저장하고 chcp 949로 콘솔 코드페이지를 파일 인코딩에 맞췄다.
#
# 2026-08-19 재구조화: 실제 사용 환경(VS Code 터미널, Windows Terminal)이
# 한글 CP949 바이트를 UTF-8로 디코드해 깨진다는 현장 보고가 들어왔다. 그래서
# .bat/config.env 계열에서 비ASCII 문자 자체를 없앴다 - 파일에 한글이 없으면
# 인코딩 문제가 성립하지 않는다. chcp는 65001(UTF-8)로 바뀌었고, 파이썬 도구가
# 내는 한글 진단은 UTF-8로 정상 출력된다. 배치 자신의 메시지는 이제 전부
# 영문이다. SCRIPT_ENCODING은 "ascii"로 남기지만, 핵심 불변조건은 인코딩
# 자체가 아니라 "비ASCII 바이트가 0"이라는 사실이다(아래 참조).
SCRIPT_ENCODING = "ascii"


def read(name: str) -> str:
    return (WIN / name).read_text(encoding=SCRIPT_ENCODING)


ALL_BATCH_FILES = (
    "install-python-packages.bat",
    "start-llama.bat",
    "start-pi.bat",
    "verify-bundle.bat",
    "verify-offline.bat",
)


def _strip_quoted(line: str) -> str:
    # 따옴표 안의 괄호는 안전하다(2026-08-18 윈도우 실측) - 큰따옴표 구간을
    # 통째로 지워서 그 안의 ( ) 는 검사 대상에서 뺀다.
    out = []
    in_quotes = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
            out.append(ch)
            continue
        out.append("Q" if in_quotes else ch)
    return "".join(out)


def _unescaped_parens_in_blocks(body: str) -> list[str]:
    # cmd.exe는 if/for/else의 ( ... ) 블록 안에서, echo/rem 줄에 있는 따옴표
    # 밖 괄호를 "^로 이스케이프하지 않으면" 블록 경계로 오해한다. 2026-08-18
    # 윈도우 실측: 짝이 맞는 괄호(한 줄 안에 ( 와 ) 가 모두 있는 경우)조차
    # 블록을 조기에 닫아 "...은(는) 예상되지 않았습니다"로 죽는다 - 매칭
    # 여부와 무관하게 이스케이프가 필요하다. 블록 경계는 "if ...(", "for
    # ...(", "else (" 로 끝나는 줄이 열고, 줄 앞이 ")" 인 줄이 닫는다(이
    # 파일들의 실제 스타일 - 다른 형태의 블록은 여기서 다루지 않는다).
    offenders = []
    depth = 0
    opener = re.compile(r"(^|\s)(if\b.*|for\b.*|else)\s*\(\s*$", re.IGNORECASE)
    for raw in body.split("\n"):
        line = raw.rstrip("\r")
        stripped = line.strip()
        lower = stripped.lower()
        is_opener = bool(opener.search(stripped))
        is_closer = stripped.startswith(")")
        if depth > 0 and (lower.startswith("echo") or lower.startswith("rem")):
            content = _strip_quoted(line)
            for idx, ch in enumerate(content):
                if ch not in "()":
                    continue
                if idx > 0 and content[idx - 1] == "^":
                    continue
                offenders.append(line)
                break
        if is_closer:
            depth = max(0, depth - 1)
            if re.search(r"else\s*\(\s*$", stripped, re.IGNORECASE):
                depth += 1
        elif is_opener:
            depth += 1
    return offenders


def test_no_unescaped_parens_in_echo_or_rem_lines_inside_blocks():
    # install-python-packages.bat 171행이 실측으로 걸린 함정: if 블록 안의
    # echo 줄에 이스케이프 안 된 괄호가 있으면 그 줄에서 블록이 조기 종료돼
    # 성공 경로 자체가 실행되지 않는다(2026-08-18 윈도우 실측, 축약 재현
    # 포함). 완벽한 cmd 파서는 아니다 - echo/rem 줄의 따옴표 밖 괄호만 잡는다.
    for name in ALL_BATCH_FILES:
        offenders = _unescaped_parens_in_blocks(read(name))
        assert not offenders, f"{name}: {offenders}"


def test_start_llama_pins_the_required_server_arguments():
    body = read("start-llama.bat")
    for required in ("--jinja", "--host 127.0.0.1", "-ngl 999", "--parallel 1", "-sm layer"):
        assert required in body, required


def test_start_llama_never_hardcodes_a_tensor_split():
    body = read("start-llama.bat")
    assert "-ts 1,1,1" not in body
    assert "GPU_TENSOR_SPLIT" in body


def test_start_llama_refuses_to_run_without_model_file_and_alias():
    body = read("start-llama.bat")
    assert "if not defined MODEL_FILE" in body
    assert "if not defined MODEL_ALIAS" in body


def test_start_pi_seals_offline_mode_and_the_portable_home():
    body = read("start-pi.bat")
    assert 'set "PI_OFFLINE=1"' in body
    assert 'set "PI_CODING_AGENT_DIR=%~dp0home\\agent"' in body
    assert "LLAMA_BASE_URL" in body


def test_start_pi_checks_the_binary_exists_before_anything_else():
    body = read("start-pi.bat")
    assert "if not exist" in body
    assert "bin\\pi\\pi.exe" in body


def test_start_pi_waits_for_the_model_before_launching():
    body = read("start-pi.bat")
    assert "wait_model.py" in body
    assert "errorlevel 1" in body
    index_wait = body.index("wait_model.py")
    index_pi_launch = body.rindex("bin\\pi\\pi.exe")
    assert index_wait < index_pi_launch, "모델 준비 확인이 Pi 기동보다 먼저여야 한다"


def test_batch_files_resolve_python_before_using_it():
    for name in ("start-pi.bat", "verify-bundle.bat", "verify-offline.bat", "install-python-packages.bat"):
        body = read(name)
        assert "PYTHON_CMD" in body, name
        assert "py -3.12" in body, name


def test_verify_offline_collects_every_required_piece_of_evidence():
    body = read("verify-offline.bat")
    for required in ("nvidia-smi", "verify_bundle.py", "v1/models", "pktmon", "evidence"):
        assert required in body, required


def test_manifest_verification_is_never_reimplemented_in_powershell():
    # 검증 규칙은 tools/manifest.py 하나뿐이다. 두 번째 구현이 생기면 둘이
    # 어긋나도 알 수 없다. .ps1을 순회하는 루프는 .ps1이 하나도 없으면 0회
    # 돌고 아무것도 증명하지 않으므로, 존재하지 않는다는 사실 자체를 단언한다.
    assert sorted(path.name for path in WIN.rglob("*.ps1")) == []


def test_no_script_mentions_cuda_13():
    for name in ("start-llama.bat", "start-pi.bat", "verify-bundle.bat", "verify-offline.bat", "config.env.example"):
        assert "cuda-13" not in read(name).lower()


def test_config_example_documents_every_variable_the_scripts_read():
    example = read("config.env.example")
    for variable in (
        "LLAMA_BACKEND",
        "LLAMA_PORT",
        "LLAMA_CTX",
        "MODEL_FILE",
        "MODEL_ALIAS",
        "GPU_TENSOR_SPLIT",
        "MMPROJ_FILE",
    ):
        assert variable in example, variable


def test_start_llama_wires_mmproj_conditionally():
    body = read("start-llama.bat")
    assert "MMPROJ_FILE" in body
    assert "--mmproj" in body
    assert 'set "MMPROJ_ARG="' in body
    assert "%MMPROJ_ARG%" in body
    # 실행 줄에 조건부로 채운 변수를 넣지, 고정 인자로 박아 넣지 않는다.
    assert "-sm layer %TS_ARG% %MMPROJ_ARG%" in body


def test_start_llama_refuses_to_run_with_missing_mmproj_file():
    body = read("start-llama.bat")
    assert "if defined MMPROJ_FILE if not exist" in body


def test_start_llama_never_hardcodes_the_mmproj_filename():
    # --mmproj 경로는 config.env의 MMPROJ_FILE로만 들어와야 한다.
    body = read("start-llama.bat")
    assert "mmproj-Qwen3.8-27B-BF16.gguf" not in body


def test_config_example_documents_mmproj_file():
    example = read("config.env.example")
    assert "MMPROJ_FILE" in example


def test_batch_files_pin_the_console_codepage_to_the_file_encoding():
    # 파일은 이제 순수 ASCII다(SCRIPT_ENCODING 주석 참조) - 그래서 콘솔을
    # UTF-8(65001)로 맞출 수 있다. chcp 65001을 @echo off 바로 다음,
    # setlocal보다 앞에 둔다.
    for name in ("start-llama.bat", "start-pi.bat", "verify-bundle.bat", "verify-offline.bat", "install-python-packages.bat"):
        body = read(name)
        assert "chcp 65001" in body, name
        assert "chcp 949" not in body, name
        index_echo_off = body.index("@echo off")
        index_chcp = body.index("chcp 65001")
        index_setlocal = body.index("setlocal")
        assert index_echo_off < index_chcp < index_setlocal, name


def test_python_callers_pin_the_output_encoding_to_the_console_codepage():
    # 콘솔이 UTF-8(65001)이므로 파이썬 출력도 UTF-8로 고정한다. 파이썬 도구
    # (tools/*.py)는 UTF-8 소스이고 한글 진행 메시지를 그대로 낸다 - 콘솔이
    # UTF-8이면 정상 출력되고, evidence\\manifest-check.txt 같은 리다이렉트
    # 파일도 UTF-8로 남는다.
    for name in ("start-pi.bat", "verify-bundle.bat", "verify-offline.bat", "install-python-packages.bat"):
        body = read(name)
        assert "PYTHONIOENCODING=utf-8" in body, name
        index_pin = body.index("PYTHONIOENCODING=utf-8")
        index_python_call = body.index("%PYTHON_CMD%")
        assert index_pin < index_python_call, name


def test_batch_files_carry_no_byte_order_mark():
    # BOM은 cmd.exe에서 @echo off를 포함한 첫 줄을 깨뜨린다.
    for name in ("start-llama.bat", "start-pi.bat", "verify-bundle.bat", "verify-offline.bat", "config.env.example", "install-python-packages.bat"):
        raw = (WIN / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), name


def test_batch_files_use_crlf_line_endings():
    # cmd.exe는 배치 파일을 실행하면서 바이트 오프셋으로 다시 읽는다. 줄바꿈이 LF
    # 뿐이고 줄에 비ASCII(한글) 문자가 있으면 그 다음 줄부터 파싱이 어긋난다.
    # 2026-08-18 윈도우 실측: LF 판 start-llama.bat은 config.env 호출과 echo가
    # 전부 깨졌고("'?라'은(는) 내부 또는 외부 명령이 아닙니다"), 바이트만 CRLF로
    # 바꾼 같은 파일은 정상 동작했다.
    for name in ("start-llama.bat", "start-pi.bat", "verify-bundle.bat", "verify-offline.bat", "config.env.example", "install-python-packages.bat"):
        raw = (WIN / name).read_bytes()
        assert b"\n" in raw, name
        assert raw.replace(b"\r\n", b"") .count(b"\n") == 0, f"{name}에 CR 없는 LF 줄이 있다"


def test_batch_files_carry_zero_non_ascii_bytes():
    # 2026-08-19 재구조화의 핵심 불변조건. VS Code 터미널·Windows Terminal이
    # UTF-8로 디코드해 CP949 배치 출력을 깨뜨린다는 현장 보고 때문에, 이
    # 번들의 .bat/config 계열에서 비ASCII 바이트 자체를 없앴다. 파일에
    # 한글이 없으면 콘솔 코드페이지와 파일 인코딩이 어긋날 여지도 없다.
    # 인코딩이 "무엇"인지가 아니라 비ASCII 바이트 수가 0인지를 직접 센다.
    for name in ("start-llama.bat", "start-pi.bat", "verify-bundle.bat", "verify-offline.bat", "config.env.example", "install-python-packages.bat"):
        raw = (WIN / name).read_bytes()
        non_ascii = [byte for byte in raw if byte > 0x7F]
        assert non_ascii == [], f"{name}: {len(non_ascii)} non-ASCII byte(s)"
        for number, line in enumerate(raw.split(b"\r\n"), start=1):
            assert b"\n" not in line, f"{name}:{number}"


# --- B3: 후행 역슬래시가 붙은 %ROOT%를 외부 실행 파일 인자로 넘기지 않는다 ---

def _external_invocation_lines(body: str) -> list[str]:
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("rem "):
            continue
        if "%PYTHON_CMD%" in stripped or ".exe" in stripped.lower():
            lines.append(stripped)
    return lines


def test_no_batch_file_passes_a_trailing_backslash_root_to_a_program():
    # 실측(2026-08-18, 윈도우 CPython):
    #   --root "C:\\pi_agent\\"   -> ARGV: ['--root', 'C:\\pi_agent"']    (깨짐)
    #   --root "C:\\pi_agent\\."  -> ARGV: ['--root', 'C:\\pi_agent\\.']  (정상)
    # %~dp0는 항상 역슬래시로 끝나므로 "%ROOT%"를 그대로 넘기면 닫는 따옴표가
    # 이스케이프되어 argv가 깨진다.
    for name in ("start-llama.bat", "start-pi.bat", "verify-bundle.bat", "verify-offline.bat", "install-python-packages.bat"):
        body = read(name)
        assert '--root "%ROOT%"' not in body, name
        for line in _external_invocation_lines(body):
            assert '"%ROOT%"' not in line, f"{name}: {line}"


def test_verify_offline_terminates_the_root_path_before_passing_it():
    assert '--root "%ROOT%."' in read("verify-offline.bat")


def test_verify_bundle_terminates_the_root_path_before_passing_it():
    # win/README-폐쇄망.md 1단계가 파이썬을 직접 부르던 것을 이 스크립트로
    # 대체한 이유가 바로 이 함정이다(verify-offline.bat과 같은 실측).
    assert '--root "%ROOT%."' in read("verify-bundle.bat")


def test_verify_bundle_calls_verify_bundle_py_with_pinned_encoding():
    body = read("verify-bundle.bat")
    assert "tools\\verify_bundle.py" in body
    assert "PYTHONIOENCODING=utf-8" in body
    assert "%PYTHON_CMD%" in body
    index_pin = body.index("PYTHONIOENCODING=utf-8")
    index_call = body.index("tools\\verify_bundle.py")
    assert index_pin < index_call


def test_verify_bundle_returns_the_python_exit_code_unchanged():
    body = read("verify-bundle.bat")
    assert "exit /b %errorlevel%" in body
    index_call = body.index("tools\\verify_bundle.py")
    index_exit = body.index("exit /b %errorlevel%")
    assert index_call < index_exit


# --- B4: verify-offline.bat이 스스로 프로브를 쓰고, 미설정을 거부하고, 루트로 이동한다 ---

def test_verify_offline_writes_the_probe_file_it_asks_the_model_to_read(tmp_path):
    body = read("verify-offline.bat")
    assert 'set "PROBE=%EV%\\probe.txt"' in body
    assert '> "%PROBE%" echo ' in body, "프로브 파일을 스크립트가 직접 쓰지 않는다"
    index_write = body.index('> "%PROBE%" echo ')
    index_prompt = body.index("-p \"%PROBE%")
    assert index_write < index_prompt, "프로브를 쓰기 전에 읽으라고 시킨다"
    # 프롬프트에는 절대 경로(%PROBE%)가 들어가야 한다. 상대 경로 evidence\probe.txt는 금지.
    assert "evidence\\probe.txt" not in body


def test_verify_offline_probe_word_is_unique_and_checked_in_the_summary():
    body = read("verify-offline.bat")
    marker = "NARWHAL-7Q2X"
    assert f'> "%PROBE%" echo {marker}' in body
    # 요약 안내에도 같은 낱말이 나와야 운영자가 무엇을 대조할지 안다.
    assert body.count(marker) >= 2


def test_verify_offline_refuses_to_run_without_the_model_identifiers():
    body = read("verify-offline.bat")
    assert "if not defined MODEL_ALIAS" in body
    assert "if not defined PI_MODEL_ID" in body
    index_guard = max(body.index("if not defined MODEL_ALIAS"), body.index("if not defined PI_MODEL_ID"))
    index_pi = body.index("bin\\pi\\pi.exe")
    assert index_guard < index_pi


def test_batch_files_that_still_need_the_bundle_root_move_there_first():
    # cd가 없으면 상대 경로가 호출 시점의 cwd 기준으로 풀린다.
    # start-pi.bat은 여기서 제외한다 - 아래 test_start_pi_does_not_change_directory 참고.
    for name in ("start-llama.bat", "verify-offline.bat", "install-python-packages.bat"):
        body = read(name)
        assert 'cd /d "%ROOT%"' in body, name
        assert body.index('cd /d "%ROOT%"') < body.index("call :load_config"), name


def test_start_pi_does_not_change_directory():
    # 2026-08-18 재리뷰: start-pi.bat의 모든 경로는 이미 %ROOT% 절대 경로라
    # cd가 사 주는 것이 없는데, Pi 자신의 문서(bin/pi/docs/security.md,
    # usage.md)는 프로젝트 컨텍스트·트러스트 판정·세션 저장 위치를 cwd
    # 기준으로 잡는다고 명시한다. start-pi.bat은 운영자의 상시 진입점이므로
    # cd가 있으면 어느 폴더에서 실행하든 항상 번들 루트가 작업 프로젝트가
    # 되어, 정작 코딩 대상 폴더를 Pi가 보지 못한다. "빠졌다"고 되돌리지 마라 -
    # 의도적 제거다. verify-offline.bat과 start-llama.bat은 cd를 그대로
    # 유지한다: 둘 다 pi.exe처럼 cwd를 트러스트 판정에 쓰는 문서가 없고,
    # start-llama.bat이 띄우는 llama-server.exe는 상시 진입점이 아니라 창을
    # 띄운 채 계속 사는 백그라운드 서버라 실행 폴더가 운영자 작업 폴더와
    # 섞일 일이 없다 - 이 좁은 수정의 범위 밖이라 건드리지 않았다.
    body = read("start-pi.bat")
    assert 'cd /d "%ROOT%"' not in body


# --- B2: 정적 제공자 선언으로 단일 모델 모드 llama-server를 인식시킨다 ---

def test_models_json_declares_the_local_openai_compatible_provider():
    import json

    document = json.loads((WIN / "models.json").read_text(encoding="utf-8"))
    provider = document["providers"]["local"]
    assert provider["baseUrl"] == "http://127.0.0.1:8080/v1"
    assert provider["api"] == "openai-completions"
    assert provider["apiKey"], "키 없는 로컬 서버라도 더미 값이 있어야 /model에 나타난다"
    # 상류 문서가 Ollama/vLLM 같은 OpenAI 호환 서버에 대해 명시하는 두 플래그.
    assert provider["compat"]["supportsDeveloperRole"] is False
    assert provider["compat"]["supportsReasoningEffort"] is False
    assert [model["id"] for model in provider["models"]] == ["qwen3.8-27b"]


def test_models_json_base_url_port_matches_the_configured_default():
    import json
    import re

    document = json.loads((WIN / "models.json").read_text(encoding="utf-8"))
    base_url = document["providers"]["local"]["baseUrl"]
    example = read("config.env.example")
    port = re.search(r'set "LLAMA_PORT=(\d+)"', example).group(1)
    assert f":{port}/" in base_url, "models.json은 환경변수를 읽지 않는다 - 포트가 어긋나면 조용히 실패한다"


def test_pi_model_id_is_the_provider_key_joined_to_the_alias():
    import json
    import re

    document = json.loads((WIN / "models.json").read_text(encoding="utf-8"))
    provider_key = next(iter(document["providers"]))
    model_id = document["providers"][provider_key]["models"][0]["id"]
    example = read("config.env.example")
    configured = re.search(r'set "PI_MODEL_ID=([^"]+)"', example).group(1)
    assert configured == f"{provider_key}/{model_id}"


def test_both_pi_callers_refresh_models_json_from_the_verified_root_copy():
    # 원본은 매니페스트 해시 범위 안(번들 루트)에 있고, 가변 영역인 home\agent\로
    # 매번 덮어쓴다. 그래야 설정이 항상 검증된 원본에서 나온다.
    for name in ("start-pi.bat", "verify-offline.bat"):
        body = read(name)
        assert 'copy /y "%ROOT%models.json" "%PI_CODING_AGENT_DIR%\\models.json"' in body, name
        assert 'if not exist "%PI_CODING_AGENT_DIR%" mkdir "%PI_CODING_AGENT_DIR%"' in body, name
        assert 'if not exist "%ROOT%models.json"' in body, name
        # 복사는 서브루틴에 있으므로 실행 순서는 call 위치로 본다.
        index_call = body.index("call :place_models_json")
        index_pi = body.index('"%ROOT%bin\\pi\\pi.exe" --offline')
        assert index_call < index_pi, name


def test_pi_is_launched_with_the_provider_qualified_model_id():
    assert '--model "%PI_MODEL_ID%"' in read("start-pi.bat")
    assert '--model "%PI_MODEL_ID%"' in read("verify-offline.bat")
    for name in ("start-pi.bat", "verify-offline.bat"):
        assert '--model "%MODEL_ALIAS%"' not in read(name), name


def test_wait_model_still_polls_the_bare_alias_on_v1_models():
    # 단일 모델 모드 llama-server의 /v1/models는 --alias 값을 그대로 노출한다.
    # 제공자 접두사는 Pi 쪽 이름이지 서버 쪽 이름이 아니다.
    body = read("start-pi.bat")
    assert '--alias "%MODEL_ALIAS%"' in body
    assert "/v1/models" not in body  # 엔드포인트는 wait_model.py가 정한다


# --- B1: 번들 내장 파이썬을 가장 먼저 쓴다 ---

def test_batch_files_prefer_the_bundled_python_runtime():
    for name in ("start-pi.bat", "verify-bundle.bat", "verify-offline.bat"):
        body = read(name)
        assert 'if not exist "%ROOT%bin\\python\\python.exe" goto :resolve_python_system' in body, name
        assert 'set "PYTHON_CMD="%ROOT%bin\\python\\python.exe""' in body, name
        index_bundled = body.index("bin\\python\\python.exe")
        index_py_launcher = body.index("py -3.12")
        index_bare = body.index("python -c")
        assert index_bundled < index_py_launcher < index_bare, name


def test_user_supplied_python_cmd_still_wins():
    for name in ("start-pi.bat", "verify-bundle.bat", "verify-offline.bat"):
        body = read(name)
        index_user = body.index("if defined PYTHON_CMD goto :eof")
        index_bundled = body.index("bin\\python\\python.exe")
        assert index_user < index_bundled, name


# --- Minor 3: 모델 적재 타임아웃을 config.env로 뺀다 ---

def test_model_load_timeout_is_configurable_with_a_600_second_default():
    body = read("start-pi.bat")
    assert "--timeout 600" not in body, "타임아웃이 .bat에 하드코딩돼 있다"
    assert 'if not defined MODEL_LOAD_TIMEOUT set "MODEL_LOAD_TIMEOUT=600"' in body
    assert "--timeout %MODEL_LOAD_TIMEOUT%" in body
    assert 'set "MODEL_LOAD_TIMEOUT=600"' in read("config.env.example")


def test_config_example_documents_the_new_variables():
    example = read("config.env.example")
    for variable in ("PI_MODEL_ID", "PI_PROVIDER", "MODEL_LOAD_TIMEOUT", "PYTHON_CMD"):
        assert variable in example, variable


def test_config_env_is_loaded_through_an_executable_copy():
    # cmd의 call은 .bat/.cmd 확장자만 배치로 실행한다. `call "...\config.env"`는
    # 아무 일도 하지 않고 errorlevel 0으로 돌아온다(2026-08-18 윈도우 실측:
    # config.env의 모든 set이 무시되어 MODEL_ALIAS가 끝내 비어 있었다).
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "install-python-packages.bat"):
        body = read(name)
        assert 'call "%ROOT%config.env"' not in body, name
        assert "call :load_config" in body, name
        assert 'copy /y "%ROOT%config.env" "%ROOT%home\\agent\\config.cmd"' in body, name
        assert 'call "%ROOT%home\\agent\\config.cmd"' in body, name


def test_config_files_are_stored_in_the_declared_script_encoding():
    # SCRIPT_ENCODING이 "ascii"이므로, 선언한 인코딩으로 읽힌다는 것 자체가
    # 비ASCII 바이트가 없다는 뜻이다(위 test_batch_files_carry_zero_non_ascii_bytes와
    # 같은 불변조건을 다른 경로로 다시 확인한다).
    for name in ("start-llama.bat", "start-pi.bat", "verify-bundle.bat", "verify-offline.bat", "config.env.example", "install-python-packages.bat"):
        raw = (WIN / name).read_bytes()
        raw.decode(SCRIPT_ENCODING)


# --- 2026-08-18 재리뷰: pi.exe를 띄우기 전에 LLAMA_BASE_URL을 지운다 ---

def test_llama_base_url_is_cleared_before_launching_pi():
    # LLAMA_BASE_URL이 설정된 채로 pi.exe가 뜨면 내장 llama.cpp 제공자가
    # 인증된 것으로 취급되어 모델 목록에 살아난다. 그 제공자는 라우터 API로
    # 모델을 열거하므로 "Server is not running in llama.cpp router mode"를
    # 뱉는다 - models.json 정적 제공자로 우회하려던 바로 그 실패의 재발이다.
    # 이 변수를 실제로 읽는 곳은 wait_model.py뿐이고(그마저 --base-url
    # 인자로도 받으므로 환경변수가 꼭 필요하지 않다), pi.exe 호출 전에는
    # 지운다. bin\\pi\\pi.exe는 start-pi.bat의 존재 확인에서 먼저 한 번 더
    # 나오므로(기존 테스트가 쓰는 방식을 따라) 마지막 출현을 기준으로 본다.
    for name in ("start-pi.bat", "verify-offline.bat"):
        body = read(name)
        assert 'set "LLAMA_BASE_URL="' in body, name
        index_clear = body.index('set "LLAMA_BASE_URL="')
        index_pi_launch = body.rindex("bin\\pi\\pi.exe")
        assert index_clear < index_pi_launch, name


# --- 파이썬 오프라인 휠하우스 설치 스크립트 (packages_win\) ---

def test_install_python_packages_blocks_the_network_and_pins_versions():
    # --no-index가 없으면 pip이 PyPI로 새고, --constraint가 없으면 다중 버전이
    # 공존하는 휠셋(packages_win\py312)에서 어느 버전이 뽑힐지 결정론적이지 않다.
    body = read("install-python-packages.bat")
    assert "--no-index" in body
    assert "--find-links" in body
    assert "--constraint" in body
    assert "packages_win\\py312" in body
    assert "packages_win\\constraints-py312.txt" in body
    assert "packages_win\\requirements.txt" in body


def test_install_python_packages_never_reaches_an_index():
    # --index-url 자체가 없어야 하고, "pip install"이 나오는 모든 줄에는
    # --no-index가 같은 줄에 있어야 한다 - 두 번째 pip 호출을 누가 추가하면서
    # --no-index를 빠뜨리는 회귀를 잡는다.
    body = read("install-python-packages.bat")
    assert "--index-url" not in body
    assert "-i http" not in body
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("rem "):
            continue
        if "pip install" in stripped.lower():
            assert "--no-index" in stripped, stripped


def test_install_python_packages_defaults_to_an_isolated_venv():
    # 기본값이 --user였을 때는 %APPDATA%\\Python\\Python312\\site-packages 에
    # numpy/pandas를 심어 그 사용자의 모든 Python 3.12 실행에 영향을 줬다.
    # 사내 스크립트가 numpy<2를 쓰고 있으면 즉시 깨지고 되돌리는 절차도 없다.
    # 그래서 격리가 기본이고, 전역을 바꾸는 쪽을 인자로 명시하게 한다.
    body = read("install-python-packages.bat")
    # "set "USE_VENV=1"" 문자열만 보면 인자 처리 줄(if /I "%~1"=="venv" set
    # "USE_VENV=1")도 같은 문자열을 담고 있어 그 줄만 남기고 진짜 기본값
    # 대입(인자 처리보다 앞)을 0으로 바꿔도 통과한다 - 인자 처리가 시작되기
    # 전(첫 "if /I "%~1"==" 줄 앞) 구간을 앵커로 삼는다.
    index_first_arg_check = body.index('if /I "%~1"==')
    prefix = body[:index_first_arg_check]
    assert 'set "USE_VENV=1"' in prefix, "기본값이 격리 설치여야 한다"
    assert 'set "VENV_DIR=%ROOT%.venv"' in body
    assert 'if /I "%~1"=="--user" set "USE_VENV=0"' in body, "--user는 인자로 명시할 때만 쓰인다"
    # 무인자 경로에서 --user가 켜지는 곳이 없어야 한다: INSTALL_SCOPE에 --user를
    # 넣는 줄은 --user 분기(:scope_user) 안에만 있다.
    scope_user = body[body.index("\n:scope_user\n") : body.index("\n:scope_done\n")]
    assert 'set "INSTALL_SCOPE=--user"' in scope_user
    assert body.count('set "INSTALL_SCOPE=--user"') == 1
    assert body.index('set "INSTALL_SCOPE="') < body.index("\n:scope_user\n")


def test_install_python_packages_actually_creates_the_venv():
    # 이 줄이 통째로 "echo skip" 같은 것으로 바뀌어도 이 검사 이전까지는
    # 아무것도 venv가 실제로 만들어지는지 보지 않았다 - errorlevel 처리와
    # [FAIL] 메시지만 있으면 그 앞의 실제 생성 명령이 없어도 통과했다.
    body = read("install-python-packages.bat")
    venv_guard = body[
        body.index('if not exist "%VENV_DIR%\\Scripts\\python.exe" (') :
        body.index('\nset "PYTHON_CMD="%VENV_DIR%')
    ]
    assert '%PYTHON_CMD% -m venv "%VENV_DIR%"' in venv_guard


def test_install_python_packages_warns_that_user_scope_changes_the_global_python():
    # --user를 고른 운영자는 무엇을 감수하는지 콘솔에서 읽을 수 있어야 한다.
    body = read("install-python-packages.bat")
    scope_user = body[body.index("\n:scope_user\n") : body.index("\n:scope_done\n")]
    assert "[warn]" in scope_user
    assert "site-packages" in scope_user
    assert "Python312" in scope_user, "어느 경로가 바뀌는지 말해야 한다"


def test_install_python_packages_suppresses_the_script_location_noise():
    body = read("install-python-packages.bat")
    assert "--no-warn-script-location" in body


def test_install_python_packages_writes_evidence_not_just_an_exit_code():
    # 이 번들의 규칙: 성공 기준은 종료 코드가 아니라 evidence\\에 남은 증거다.
    body = read("install-python-packages.bat")
    assert "evidence" in body
    assert "python-packages-install.txt" in body
    assert "python-packages-check.txt" in body


def test_install_python_packages_verifies_every_direct_dependency_not_just_five():
    # 다섯 개를 한 줄로 묶어 임포트하던 이전 방식은 lightgbm·catboost·shap·
    # pyarrow·pyreadstat·seaborn·sksurv가 깨져 있어도 증거가 초록이었다.
    # 이제 requirements.txt의 직접 의존 전부를 하나씩 임포트한다.
    body = read("install-python-packages.bat")
    assert "-c \"import pandas, numpy, lifelines, statsmodels, sklearn" not in body
    assert "tools\\check_imports.py" in body
    assert '--requirements "%REQUIREMENTS%"' in body
    assert "python-packages-check.txt" in body
    index_check = body.index("check_imports.py")
    index_evidence = body.index('"%EV%\\python-packages-check.txt"')
    assert index_check < index_evidence, "임포트 결과가 증거 파일로 가야 한다"
    # 위 두 인덱스는 다음 줄의 "type" 호출도 "%EV%\python-packages-check.txt"를
    # 담고 있어서, check_imports.py 호출 자체의 "> 리디렉션"을 지워도
    # (type 줄은 그대로이므로) 통과했다. check_imports.py를 실행하는 그
    # 줄 자체에 파일로의 리디렉션이 있는지 직접 본다.
    check_line = next(
        line for line in body.splitlines() if "check_imports.py" in line
    )
    assert '> "%EV%\\python-packages-check.txt"' in check_line, check_line


def test_install_python_packages_targets_system_python_not_the_embedded_one():
    # 임베디드 배포(bin\\python\\python.exe)에는 pip이 없다 - 다른 .bat들과
    # 달리 이 스크립트는 그 경로를 절대 먼저 확인하지 않는다. 대신 py -3.12를
    # 우선하고 python으로 폴백한다.
    body = read("install-python-packages.bat")
    assert 'if not exist "%ROOT%bin\\python\\python.exe" goto :resolve_python_system' not in body
    assert 'set "PYTHON_CMD="%ROOT%bin\\python\\python.exe""' not in body
    index_py_launcher = body.index("py -3.12")
    index_bare_python = body.index("python -c")
    assert index_py_launcher < index_bare_python


def test_install_python_packages_validates_even_a_user_supplied_python_cmd():
    # 예전에는 :resolve_python이 "if defined PYTHON_CMD goto :eof"로 시작해서
    # config.env 값이 무조건 이겼다. 그런데 config.env.example과 README는
    # "비워두면 번들 내장 bin\\python\\python.exe를 먼저 쓴다"고 안내했으므로,
    # 그 안내대로 임베디드 파이썬 경로를 적은 운영자는 pip이 없는 파이썬으로
    # 설치를 시도하게 됐다. 지정된 것도 검사를 통과해야 이긴다.
    body = read("install-python-packages.bat")
    assert "if defined PYTHON_CMD goto :eof" not in body, "지정값이 검사를 건너뛰면 안 된다"
    assert "if defined PYTHON_CMD goto :resolve_python_configured" in body
    index_configured = body.index("\n:resolve_python_configured\n")
    index_validate_call = body.index("\n:resolve_python_validate\n")
    assert index_configured < index_validate_call
    # 지정 경로도 자동 탐색 경로도 같은 검사로 수렴한다.
    resolve = body[body.index("\n:resolve_python\n") :]
    assert resolve.count("goto :resolve_python_validate") == 3


def test_install_python_packages_requires_python_312_with_pip():
    # (a) cp312 휠 155개는 3.13에서 전부 "not a supported wheel"로 실패하는데
    #     예전 폴백은 "import sys"만 보고 통과시킨 뒤 "3.12를 찾지 못했다"고
    #     엉뚱한 메시지를 냈다. (b) 임베디드 배포에는 pip이 없다.
    body = read("install-python-packages.bat")
    validate = body[body.index("\n:validate_python\n") : body.index("\n:resolve_python\n")]
    assert "sys.version_info[:2] == (3, 12)" in validate
    assert "import pip" in validate
    assert validate.count("exit /b 1") == 3, "세 실패 각각이 따로 종료해야 한다"
    assert "not Python 3.12" in validate
    assert "this Python has no pip" in validate
    assert "print(sys.version)" in validate, "무엇이 잡혔는지 실제 버전을 보여야 한다"
    # venv 파이썬도 같은 검사를 통과해야 한다.
    assert body.count("call :validate_python") == 2


def test_install_python_packages_fails_closed_without_a_python():
    # 이전 판은 파일 어딘가에 [FAIL]과 exit /b 1이 있는지만 봐서 이 저장소의
    # 거의 모든 .bat이 통과했다. 파이썬 탐색이 실패하는 그 경로를 직접 본다.
    body = read("install-python-packages.bat")
    resolve = body[body.index("\n:resolve_python\n") : body.index("\n:resolve_python_configured\n")]
    lines = [line.strip() for line in resolve.splitlines() if line.strip()]
    # py -3.12 도 python 도 안 되면 곧바로 실패해야 한다: 두 폴백 뒤에 남는
    # 것은 [FAIL] 안내와 exit /b 1 뿐이고, 그 사이에 성공 경로가 없어야 한다.
    tail = lines[lines.index("python -c \"import sys\" >nul 2>&1") :]
    assert any(line.startswith("echo [FAIL]") for line in tail)
    assert tail[-1] == "exit /b 1", tail[-1]
    assert 'set "PYTHON_CMD=' not in "\n".join(tail[tail.index("exit /b 1") :])
    # 호출부가 그 실패를 삼키지 않아야 한다.
    assert "call :resolve_python" in body
    index_call = body.index("call :resolve_python")
    assert "if errorlevel 1 exit /b 4" in body[index_call : index_call + 120]


def test_install_python_packages_refuses_to_run_without_the_wheelhouse():
    body = read("install-python-packages.bat")
    assert 'if not exist "%PKG_DIR%"' in body
    assert 'if not exist "%CONSTRAINT%"' in body
    assert 'if not exist "%REQUIREMENTS%"' in body


# --- Pi 확장/스킬 패키지 (pi-packages\) - superpowers, pi-subagents, rpiv-* ---
# 조사(pi-packages-research.md): pi.exe는 로드 시점에 npm/git이 전혀 필요
# 없고, PI_CODING_AGENT_DIR\npm\, \git\ 구조로만 놓이면 그대로 인식한다.
# 그래서 여기서 새로 설치하지 않고, 사전 설치한 트리를 pi-packages\에 실어
# 와서 매 실행마다 home\agent\로 동기화한다 - models.json과 같은 관용구다.

def test_start_pi_syncs_pi_packages_before_launching_pi():
    body = read("start-pi.bat")
    assert "pi-packages" in body
    assert "call :sync_packages" in body
    index_sync = body.index("call :sync_packages")
    index_pi_launch = body.rindex("bin\\pi\\pi.exe")
    assert index_sync < index_pi_launch, "패키지 동기화가 Pi 기동보다 먼저여야 한다"


def test_pi_package_sync_runs_after_models_json_is_placed():
    # 순서 자체가 정답을 좌우하진 않지만, models.json 배치와 같은 계열의
    # "기동 전 설정 배치" 단계이므로 place_models_json 바로 뒤에 둔다.
    body = read("start-pi.bat")
    index_models = body.index("call :place_models_json")
    index_sync = body.index("call :sync_packages")
    assert index_models < index_sync


def test_pi_package_sync_copies_npm_and_git_subtrees_verbatim():
    # 조사 결과가 명시한 대로 npm\, git\ 하위 구조를 임의로 바꾸지 않는다 -
    # PI_CODING_AGENT_DIR\npm\, \git\ 이 아니면 pi.exe가 패키지를 찾지 못한다.
    body = read("start-pi.bat")
    assert 'xcopy "%ROOT%pi-packages\\npm" "%PI_CODING_AGENT_DIR%\\npm\\"' in body
    assert 'xcopy "%ROOT%pi-packages\\git" "%PI_CODING_AGENT_DIR%\\git\\"' in body


def _sync_packages_subroutine_body(body: str) -> str:
    # read()는 read_text()를 거치므로 CRLF가 이미 LF로 정규화돼 있다(다른
    # 테스트들도 body를 이 형태로 다룬다). ":sync_packages"는 "call :sync_packages"
    # 호출부에도 부분 문자열로 나타나므로, 레이블 정의 자체(줄 앞)를 앵커로
    # 삼는다. ":load_config"도 같은 이유로 "call :load_config"가 파일 맨
    # 앞에 먼저 나온다.
    # (이전 판은 여기서 "sync_packages가 load_config보다 먼저 정의돼야 한다"고
    #  단언했다. 배치의 서브루틴 정의 순서는 동작과 무관하다 - 앵커를 고르는
    #  방법일 뿐인데 요구사항처럼 읽혀서 지웠다.)
    return body[body.index("\n:sync_packages\n") : body.index("\n:load_config\n")]


def _xcopy_lines(sync_body: str) -> list[str]:
    lines = [line.strip() for line in sync_body.splitlines()]
    return [line for line in lines if line.lower().startswith("xcopy ")]


def test_pi_package_sync_destination_is_never_a_hardcoded_absolute_path():
    # 동기화 대상은 %ROOT%/%PI_CODING_AGENT_DIR% 기반이어야 한다 - 이 머신
    # 전용 절대 경로가 박히면 다른 배치 위치에서 깨진다. C:\ 만 막으면
    # D:\ 로 적은 경로와 UNC(\\server\share)가 그대로 통과한다.
    for name in ("start-pi.bat", "verify-offline.bat"):
        sync_body = _sync_packages_subroutine_body(read(name))
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            assert f"{letter}:\\" not in sync_body.upper(), f"{name}: {letter}:\\"
        assert "\\\\" not in sync_body, f"{name}: UNC 경로"
        assert "%ROOT%pi-packages" in sync_body
        assert "%PI_CODING_AGENT_DIR%" in sync_body


def test_pi_package_sync_uses_xcopy_update_flag_on_every_call():
    # "이미 최신이면 매번 전량 복사하지 않는다"는 요구를 xcopy /D 하나로
    # 충족한다 - 파일 단위 비교 로직을 이 배치에 새로 만들지 않는다.
    # 서브루틴 전체에서 플래그를 한 번만 찾으면 두 번째 xcopy에 /D를
    # 빠뜨려도 통과한다. 호출마다 줄 단위로 본다.
    for name in ("start-pi.bat", "verify-offline.bat"):
        calls = _xcopy_lines(_sync_packages_subroutine_body(read(name)))
        assert len(calls) == 2, f"{name}: {calls}"
        for call in calls:
            assert " /D " in call or call.endswith(" /D"), f"{name}: {call}"
            # git 클론의 .git은 윈도우에서 숨김(Hidden) 속성이 붙는다
            # (2026-08-18 실측) - /H가 없으면 xcopy가 통째로 건너뛴다.
            assert " /H " in call or call.endswith(" /H"), f"{name}: {call}"
            assert " /E " in call or call.endswith(" /E"), f"{name}: {call}"


def test_pi_package_sync_survives_a_locked_destination_that_already_has_packages():
    # xcopy 실패에 무조건 exit /b 7이면 다른 Pi 세션이 파일을 잠그는 순간
    # 두 번째 기동이 아예 안 된다. 이미 패키지가 있으면 경고 후 계속하고,
    # 대상이 비어 있을 때만 실패한다.
    for name in ("start-pi.bat", "verify-offline.bat"):
        sync_body = _sync_packages_subroutine_body(read(name))
        # xcopy는 파일 복사에 실패하기 전에 디렉터리 골격을 먼저 만든다
        # (2026-08-18 윈도우 실측) - 그래서 "node_modules 폴더가 있다"는
        # 전송이 손상됐을 때도 참이 될 수 있다. 패키지 하나가 실제로
        # 놓였는지를 구체적 파일로 본다: settings.packages.json이 요구하는
        # pi-subagents(npm)와 obra/superpowers(git)다.
        assert (
            'if exist "%PI_CODING_AGENT_DIR%\\npm\\node_modules\\pi-subagents\\package.json"'
            in sync_body
        ), name
        assert (
            'if exist "%PI_CODING_AGENT_DIR%\\git\\github.com\\obra\\superpowers\\package.json"'
            in sync_body
        ), name
        assert sync_body.count("[warn]") >= 2, name
        # 실패로 끝나는 길도 여전히 남아 있어야 한다(대상이 비었을 때).
        assert sync_body.count("[FAIL]") >= 2, name


def test_pi_package_sync_continue_check_is_never_satisfied_by_an_empty_directory():
    # xcopy가 대상 디렉터리 골격만 만들고 파일 복사에 실패하는 실측 시나리오를
    # 다시 회귀시키지 않기 위한 앵커: "계속한다" 판정에 쓰이는 exist 검사가
    # node_modules/github.com 디렉터리 자체가 아니라 그 밑의 구체적 파일을
    # 가리켜야 한다 - 디렉터리만 가리키는 옛 판정이 되돌아오면 잡는다.
    for name in ("start-pi.bat", "verify-offline.bat"):
        sync_body = _sync_packages_subroutine_body(read(name))
        assert 'if exist "%PI_CODING_AGENT_DIR%\\npm\\node_modules" (' not in sync_body, name
        assert 'if exist "%PI_CODING_AGENT_DIR%\\git\\github.com" (' not in sync_body, name


def test_pi_package_sync_checks_the_anchor_regardless_of_xcopys_exit_code():
    # 이 윈도우 빌드의 xcopy는 개별 파일 복사가 접근 거부로 실패해도 종료
    # 코드 0을 반환하는 사례가 실측됐다(2026-08-18) - "if not errorlevel 1
    # goto ..." 게이트가 그 경우를 성공으로 오판하면, 그 뒤에 있는 앵커
    # 파일 존재 검사에 아예 도달하지 못한다. 그래서 앵커 검사는 xcopy 호출
    # 직후, errorlevel을 묻는 어떤 goto도 거치지 않고 실행돼야 한다. 앵커
    # 검사를 "실패 분기 안"으로 되돌리는 돌연변이는 xcopy와 앵커 검사
    # 사이에 반드시 "goto"가 낀다 - 그것 하나만 본다.
    for name in ("start-pi.bat", "verify-offline.bat"):
        sync_body = _sync_packages_subroutine_body(read(name))
        for xcopy_line, anchor in (
            (
                'xcopy "%ROOT%pi-packages\\npm" "%PI_CODING_AGENT_DIR%\\npm\\" /E /H /Y /D /Q >nul',
                'if exist "%PI_CODING_AGENT_DIR%\\npm\\node_modules\\pi-subagents\\package.json"',
            ),
            (
                'xcopy "%ROOT%pi-packages\\git" "%PI_CODING_AGENT_DIR%\\git\\" /E /H /Y /D /Q >nul',
                'if exist "%PI_CODING_AGENT_DIR%\\git\\github.com\\obra\\superpowers\\package.json"',
            ),
        ):
            assert xcopy_line in sync_body, name
            assert anchor in sync_body, name
            after_xcopy = sync_body[sync_body.index(xcopy_line) + len(xcopy_line) :]
            between = after_xcopy[: after_xcopy.index(anchor)]
            assert "goto" not in between.lower(), f"{name}: {between!r}"


def test_pi_package_sync_seeds_settings_json_only_when_absent():
    # settings.json은 사용자가 /trust, /settings로 직접 고칠 수 있는 파일이라
    # models.json처럼 매번 덮어쓰면 사용자 설정이 날아간다 - 없을 때만 심는다.
    for name in ("start-pi.bat", "verify-offline.bat"):
        body = read(name)
        assert 'if exist "%PI_CODING_AGENT_DIR%\\settings.json" goto :sync_packages_compare' in body, name
        assert 'copy /y "%ROOT%pi-packages\\settings.packages.json" "%PI_CODING_AGENT_DIR%\\settings.json"' in body, name
        # 심는 copy는 한 번뿐이고, 그 앞에 "없을 때만"이라는 관문이 있다.
        index_guard = body.index('if exist "%PI_CODING_AGENT_DIR%\\settings.json" goto :sync_packages_compare')
        index_copy = body.index('copy /y "%ROOT%pi-packages\\settings.packages.json"')
        assert index_guard < index_copy, name


def test_pi_package_sync_warns_when_the_installed_package_list_drifted():
    # 갱신 경로에 감지 수단이 없던 문제: v2 번들이 패키지를 추가해도 기존
    # settings.json이 있으면 조용히 미등록되고, xcopy /D는 상류에서 삭제된
    # 파일을 지우지 않는다. 경고만 하고 덮어쓰지는 않는다.
    for name in ("start-pi.bat", "verify-offline.bat"):
        sync_body = _sync_packages_subroutine_body(read(name))
        assert "tools\\packages_diff.py" in sync_body, name
        assert '--bundled "%ROOT%pi-packages\\settings.packages.json"' in sync_body, name
        assert '--installed "%PI_CODING_AGENT_DIR%\\settings.json"' in sync_body, name
        # 대조는 이미 있는 settings.json에만 한다 - 심는 경로가 아니다.
        compare = sync_body[sync_body.index("\n:sync_packages_compare\n") :]
        assert "packages_diff.py" in compare, name
        assert "copy /y" not in compare, f"{name}: 대조가 덮어쓰기로 번지면 안 된다"


def test_verify_offline_proves_the_extensions_actually_loaded():
    # 확장 4종이 붙었다는 산출물이 이 번들의 증거 체계에 하나도 없었다 -
    # 리허설 §5-2의 수기 확인은 evidence\에 남지 않는다.
    body = read("verify-offline.bat")
    assert "call :sync_packages" in body
    assert '"%ROOT%bin\\pi\\pi.exe" list > "%EV%\\pi-packages.txt"' in body
    index_sync = body.index("call :sync_packages")
    index_list = body.index('pi.exe" list')
    assert index_sync < index_list, "동기화가 목록 확인보다 먼저여야 한다"
    # 요약 안내도 그 파일을 가리켜야 운영자가 무엇을 볼지 안다.
    assert "pi-packages.txt" in body[body.index("Check:") :]


def test_pi_packages_settings_template_declares_the_four_required_packages():
    # 정본은 win\ (git 추적)에 있다 - bin\, models\ 와 달리 이 파일은 작고
    # 사람이 리뷰할 수 있는 텍스트라 models.json과 같은 방식으로 추적한다.
    # 실제 배치본(pi-packages\settings.packages.json)은 bin\, models\ 와 같은
    # 이유로 gitignore 대상이라 fresh checkout에는 없을 수 있으므로 여기서는
    # 이 파일을 대상으로 검증하지 않는다.
    import json

    document = json.loads((WIN / "settings.packages.json").read_text(encoding="utf-8"))
    assert document["packages"] == [
        "git:github.com/obra/superpowers@v6.3.0",
        "npm:pi-subagents@0.50.0",
        "npm:@juicesharp/rpiv-todo@2.6.1",
        "npm:@juicesharp/rpiv-ask-user-question@2.6.1",
    ]


def test_bundled_and_staged_package_settings_never_diverge():
    # 정본은 win\settings.packages.json, 배치본은 pi-packages\settings.packages.json
    # 이고 start-pi.bat이 심는 것은 배치본이다. 둘이 어긋나면 리뷰한 목록과
    # 실제로 등록되는 목록이 달라지는데, 지금까지 그것을 보는 눈이 없었다.
    # 배치본은 gitignore 대상이라(상류 배포물) fresh checkout에는 없다.
    import json

    import pytest

    staged = WIN.parent / "pi-packages" / "settings.packages.json"
    if not staged.exists():
        pytest.skip("pi-packages\\는 gitignore 대상이라 스테이징한 머신에만 있다")
    canonical = json.loads((WIN / "settings.packages.json").read_text(encoding="utf-8"))
    assert json.loads(staged.read_text(encoding="utf-8")) == canonical


def test_install_python_packages_places_the_vc_runtime_lightgbm_needs():
    # lightgbm 휠은 lib_lightgbm.dll이 요구하는 VCOMP140.DLL/MSVCP140.dll을
    # 벤더링하지 않는다(scikit-learn은 sklearn\.libs\에 자체 동봉해 무사하다).
    # 번들의 VC 런타임 3종은 bin\llama-*\ 안 app-local이라 파이썬 프로세스의
    # 검색 경로에 없다.
    body = read("install-python-packages.bat")
    assert 'set "VCRUNTIME_DIR=%ROOT%packages_win\\vcruntime"' in body
    place = body[body.index("\n:place_vcruntime\n") : body.index("\n:validate_python\n")]
    assert "VCOMP140.DLL" in place
    assert "MSVCP140.dll" in place
    # 설치 위치는 venv/--user에 따라 다르므로 파이썬에게 묻는다. 이때 임포트로
    # 물으면 안 된다 - DLL이 아직 없어서 import lightgbm 자체가 실패한다.
    assert "find_spec" in place
    executable = "\n".join(
        line for line in place.splitlines() if not line.strip().lower().startswith("rem ")
    )
    assert "import lightgbm" not in executable
    # rem 주석에도 "VCOMP140.DLL"이 나온다(118행) - 그 줄만 남기고 실제
    # copy 줄만 지우는 돌연변이가 위 두 assert를 통과했었다. 주석을 뺀
    # 실행 줄에서 실제로 두 DLL을 복사하는지 각각 본다.
    assert 'copy /y "%VCRUNTIME_DIR%\\VCOMP140.DLL" "%LGB_DIR%\\bin\\"' in executable
    assert 'copy /y "%VCRUNTIME_DIR%\\MSVCP140.dll" "%LGB_DIR%\\bin\\"' in executable
    assert '"%LGB_DIR%\\bin\\"' in place
    # 실패해도 설치 전체를 멈추지 않되, 조용히 넘어가지도 않는다.
    assert "[warn]" in place
    assert "exit /b" not in place
    index_place = body.index("call :place_vcruntime")
    index_check = body.index("check_imports.py")
    assert index_place < index_check, "DLL 배치가 임포트 검증보다 먼저여야 한다"


def test_vc_runtime_for_lightgbm_is_actually_staged():
    import pytest

    vcruntime = WIN.parent / "packages_win" / "vcruntime"
    if not vcruntime.exists():
        pytest.skip("packages_win\\vcruntime\\은 gitignore 대상이라 스테이징한 머신에만 있다")
    names = {path.name.lower() for path in vcruntime.iterdir()}
    assert "vcomp140.dll" in names
    assert "msvcp140.dll" in names


def test_readme_points_at_the_bundle_root_not_the_win_directory():
    # win\ 은 매니페스트 EXCLUDED_ROOTS라 반입된 PC에 그 디렉터리가 없을 수
    # 있다. 다른 .bat은 전부 루트 기준으로 안내하는데 이 하나만 win\ 기준이었다.
    readme = (WIN / "README-폐쇄망.md").read_text(encoding="utf-8")
    assert "win\\install-python-packages.bat" not in readme
    assert "install-python-packages.bat" in readme


def test_readme_documents_the_isolated_default_and_what_user_scope_costs():
    readme = (WIN / "README-폐쇄망.md").read_text(encoding="utf-8")
    assert ".venv" in readme
    assert "--user" in readme
    # --user를 쓸 때 무엇을 감수하는지, 실행 파일이 어디 놓이는지.
    assert "Python312\\Scripts" in readme
    assert "site-packages" in readme
