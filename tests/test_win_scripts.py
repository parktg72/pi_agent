from pathlib import Path

WIN = Path(__file__).resolve().parents[1] / "win"


# cmd.exe는 UTF-8(코드페이지 65001) 배치 파일을 읽을 때 줄을 바이트 오프셋으로
# 다시 찾는다. 비ASCII 문자가 있으면 그 계산이 어긋나 줄 중간부터 명령으로
# 실행된다. 2026-08-18 윈도우 실측: UTF-8/CRLF config.env를 call하면
# "'?워'은(는) 내부 또는 외부 명령이 아닙니다" 류 오류가 6건 났고, 같은 내용을
# CP949로 인코딩하면 한 건도 나지 않았다. 그래서 이 번들의 .bat과 config 계열은
# CP949로 저장하고 chcp 949로 콘솔 코드페이지를 파일 인코딩에 맞춘다.
SCRIPT_ENCODING = "cp949"


def read(name: str) -> str:
    return (WIN / name).read_text(encoding=SCRIPT_ENCODING)


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
    for name in ("start-pi.bat", "verify-offline.bat", "install-python-packages.bat"):
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
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "config.env.example"):
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
    # 파일은 CP949로 저장한다(SCRIPT_ENCODING 주석 참조). 콘솔 코드페이지가
    # 그와 다르면 한글 echo가 깨지므로 chcp 949를 @echo off 바로 다음,
    # setlocal보다 앞에 둔다.
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "install-python-packages.bat"):
        body = read(name)
        assert "chcp 949" in body, name
        assert "chcp 65001" not in body, name
        index_echo_off = body.index("@echo off")
        index_chcp = body.index("chcp 949")
        index_setlocal = body.index("setlocal")
        assert index_echo_off < index_chcp < index_setlocal, name


def test_python_callers_pin_the_output_encoding_to_the_console_codepage():
    # 콘솔이 CP949이므로 파이썬 출력도 CP949로 고정한다. utf-8로 두면 한글
    # 진행 메시지와 evidence\\manifest-check.txt가 깨진다.
    for name in ("start-pi.bat", "verify-offline.bat", "install-python-packages.bat"):
        body = read(name)
        assert "PYTHONIOENCODING=cp949" in body, name
        index_pin = body.index("PYTHONIOENCODING=cp949")
        index_python_call = body.index("%PYTHON_CMD%")
        assert index_pin < index_python_call, name


def test_batch_files_carry_no_byte_order_mark():
    # BOM은 cmd.exe에서 @echo off를 포함한 첫 줄을 깨뜨린다.
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "config.env.example", "install-python-packages.bat"):
        raw = (WIN / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), name


def test_batch_files_use_crlf_line_endings():
    # cmd.exe는 배치 파일을 실행하면서 바이트 오프셋으로 다시 읽는다. 줄바꿈이 LF
    # 뿐이고 줄에 비ASCII(한글) 문자가 있으면 그 다음 줄부터 파싱이 어긋난다.
    # 2026-08-18 윈도우 실측: LF 판 start-llama.bat은 config.env 호출과 echo가
    # 전부 깨졌고("'?라'은(는) 내부 또는 외부 명령이 아닙니다"), 바이트만 CRLF로
    # 바꾼 같은 파일은 정상 동작했다.
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "config.env.example", "install-python-packages.bat"):
        raw = (WIN / name).read_bytes()
        assert b"\n" in raw, name
        assert raw.replace(b"\r\n", b"") .count(b"\n") == 0, f"{name}에 CR 없는 LF 줄이 있다"


def test_batch_files_that_carry_hangul_must_be_crlf_and_single_byte_safe():
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "config.env.example", "install-python-packages.bat"):
        raw = (WIN / name).read_bytes()
        raw.decode(SCRIPT_ENCODING)  # 선언한 인코딩으로 읽히지 않으면 여기서 터진다
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
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "install-python-packages.bat"):
        body = read(name)
        assert '--root "%ROOT%"' not in body, name
        for line in _external_invocation_lines(body):
            assert '"%ROOT%"' not in line, f"{name}: {line}"


def test_verify_offline_terminates_the_root_path_before_passing_it():
    assert '--root "%ROOT%."' in read("verify-offline.bat")


# --- B4: verify-offline.bat이 스스로 프로브를 쓰고, 미설정을 거부하고, 루트로 이동한다 ---

def test_verify_offline_writes_the_probe_file_it_asks_the_model_to_read(tmp_path):
    body = read("verify-offline.bat")
    assert 'set "PROBE=%EV%\\probe.txt"' in body
    assert '> "%PROBE%" echo ' in body, "프로브 파일을 스크립트가 직접 쓰지 않는다"
    index_write = body.index('> "%PROBE%" echo ')
    index_prompt = body.index("-p \"%PROBE%")
    assert index_write < index_prompt, "프로브를 쓰기 전에 읽으라고 시킨다"
    # 프롬프트에는 절대 경로(%PROBE%)가 들어가야 한다. 상대 경로 evidence\probe.txt는 금지.
    assert "evidence\\probe.txt 파일을" not in body


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
    for name in ("start-pi.bat", "verify-offline.bat"):
        body = read(name)
        assert 'if not exist "%ROOT%bin\\python\\python.exe" goto :resolve_python_system' in body, name
        assert 'set "PYTHON_CMD="%ROOT%bin\\python\\python.exe""' in body, name
        index_bundled = body.index("bin\\python\\python.exe")
        index_py_launcher = body.index("py -3.12")
        index_bare = body.index("python -c")
        assert index_bundled < index_py_launcher < index_bare, name


def test_user_supplied_python_cmd_still_wins():
    for name in ("start-pi.bat", "verify-offline.bat"):
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
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "config.env.example", "install-python-packages.bat"):
        raw = (WIN / name).read_bytes()
        raw.decode(SCRIPT_ENCODING)
        if any(byte > 0x7F for byte in raw):
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            raise AssertionError(f"{name}이 UTF-8로도 읽힌다 - CP949로 저장되지 않았다")


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


def test_install_python_packages_defaults_to_user_scope_and_documents_venv():
    body = read("install-python-packages.bat")
    assert '"INSTALL_SCOPE=--user"' in body
    assert ".venv" in body, "격리하고 싶을 때 쓸 venv 경로가 안내돼 있어야 한다"


def test_install_python_packages_writes_evidence_not_just_an_exit_code():
    # 이 번들의 규칙: 성공 기준은 종료 코드가 아니라 evidence\\에 남은 증거다.
    body = read("install-python-packages.bat")
    assert "evidence" in body
    assert "python-packages-install.txt" in body
    assert "python-packages-check.txt" in body


def test_install_python_packages_verifies_the_core_import_set():
    body = read("install-python-packages.bat")
    for module in ("pandas", "numpy", "lifelines", "statsmodels", "sklearn"):
        assert module in body, module
    assert "-c \"import pandas, numpy, lifelines, statsmodels, sklearn" in body


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


def test_install_python_packages_user_supplied_python_cmd_still_wins():
    body = read("install-python-packages.bat")
    index_user = body.index("if defined PYTHON_CMD goto :eof")
    index_py_launcher = body.index("py -3.12")
    assert index_user < index_py_launcher


def test_install_python_packages_fails_closed_without_a_python():
    body = read("install-python-packages.bat")
    assert "[FAIL]" in body
    assert "exit /b 1" in body


def test_install_python_packages_refuses_to_run_without_the_wheelhouse():
    body = read("install-python-packages.bat")
    assert 'if not exist "%PKG_DIR%"' in body
    assert 'if not exist "%CONSTRAINT%"' in body
    assert 'if not exist "%REQUIREMENTS%"' in body
