from pathlib import Path

WIN = Path(__file__).resolve().parents[1] / "win"


def read(name: str) -> str:
    return (WIN / name).read_text(encoding="utf-8")


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
    for name in ("start-pi.bat", "verify-offline.bat"):
        body = read(name)
        assert "PYTHON_CMD" in body, name
        assert "py -3.12" in body, name


def test_verify_offline_collects_every_required_piece_of_evidence():
    body = read("verify-offline.bat")
    for required in ("nvidia-smi", "verify_bundle.py", "v1/models", "pktmon", "evidence"):
        assert required in body, required


def test_manifest_verification_is_not_reimplemented_in_powershell():
    for path in WIN.rglob("*.ps1"):
        assert "Get-FileHash" not in path.read_text(encoding="utf-8"), path.name


def test_no_script_mentions_cuda_13():
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "config.env.example"):
        assert "cuda-13" not in read(name).lower()


def test_config_example_documents_every_variable_the_scripts_read():
    example = read("config.env.example")
    for variable in ("LLAMA_BACKEND", "LLAMA_PORT", "LLAMA_CTX", "MODEL_FILE", "MODEL_ALIAS", "GPU_TENSOR_SPLIT"):
        assert variable in example, variable
