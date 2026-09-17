"""2026-09-17 설정 최적화(1080 Ti x3 / RAM 128GB)와 LoRA 적재 경로의 계약.

근거는 tasks/pi-agent-lora-upgrade/artifacts/consensus.md(pane 합의)와 llama.cpp
b11010 소스다. 문자열이 있다는 것만이 아니라, 값이 실제로 어떻게 흐르는지를 본다.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "win"
sys.path.insert(0, str(ROOT / "tools"))
import config_parse
import manifest
import render_models_json

TEMPLATE = (WIN / "models.json").read_text(encoding="utf-8")


def read(name: str) -> str:
    return (WIN / name).read_text(encoding="ascii")


# --- contextWindow는 LLAMA_CTX 하나에서 나온다 ---------------------------------
# 결함 실측: config.env LLAMA_CTX=65536 인데 models.json contextWindow=32768 이었다.
# Pi는 32768 창을 가정해 max_completion_tokens를 깎고(stub 왕복 요청에서 25539 실측)
# 더 일찍 컴팩션한다 - 서버가 가진 창의 절반을 버린다. 반대로 LLAMA_CTX가 더
# 작으면 Pi가 서버보다 긴 요청을 보내 거부당한다.


def test_rendered_context_window_follows_the_server_context():
    body, problems = render_models_json.render(TEMPLATE, "8080", "qwen3.8-27b", ctx="65536")
    assert problems == []
    model = json.loads(body)["providers"]["local"]["models"][0]
    assert model["contextWindow"] == 65536


def test_max_tokens_never_exceeds_the_context_window():
    body, problems = render_models_json.render(TEMPLATE, "8080", "qwen3.8-27b", ctx="16384")
    assert problems == []
    model = json.loads(body)["providers"]["local"]["models"][0]
    assert model["contextWindow"] == 16384
    assert model["maxTokens"] <= 16384


def test_a_non_numeric_context_is_refused():
    _, problems = render_models_json.render(TEMPLATE, "8080", "qwen3.8-27b", ctx="big")
    assert problems


def test_the_cli_requires_the_context(tmp_path):
    with pytest.raises(SystemExit):
        render_models_json.main(
            ["--template", str(WIN / "models.json"), "--out", str(tmp_path / "m.json"),
             "--port", "8080", "--alias", "qwen3.8-27b"]
        )


def test_the_cli_writes_the_context_window(tmp_path):
    out = tmp_path / "models.json"
    rc = render_models_json.main(
        ["--template", str(WIN / "models.json"), "--out", str(out), "--port", "8080",
         "--alias", "qwen3.8-27b", "--model-id", "local/qwen3.8-27b", "--ctx", "65536"]
    )
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["providers"]["local"]["models"][0]["contextWindow"] == 65536


@pytest.mark.parametrize("script", ["start-pi.bat", "verify-offline.bat"])
def test_both_pi_callers_pass_the_same_context_default_as_start_llama(script):
    body = read(script)
    llama = read("start-llama.bat")
    default = re.search(r'if not defined LLAMA_CTX set "LLAMA_CTX=(\d+)"', llama).group(1)
    assert f'if not defined LLAMA_CTX set "LLAMA_CTX={default}"' in body
    render_line = next(line for line in body.splitlines() if "render_models_json.py" in line)
    assert '--ctx "%LLAMA_CTX%"' in render_line


# --- llama-server 플래그 ---------------------------------------------------------


def _server_command(body: str) -> str:
    # 존재 검사(if not exist "...llama-server.exe")가 아니라 실행 줄에서 시작한다.
    start = body.replace("\r\n", "\n").index('\n"%LLAMA_DIR%\\llama-server.exe" ^')
    body = body.replace("\r\n", "\n")
    end = body.index("exit /b %errorlevel%", start)
    return body[start:end]


def test_flash_attention_is_left_to_the_device_probe():
    # b11010 ggml-cuda/fattn.cu: 텐서코어가 없는 Pascal은 tile/vec 커널을 쓰므로
    # auto는 enabled로 풀린다. on은 src/llama-context.cpp의 장치 probe를 건너뛰어
    # 지원이 안 되면 연산이 CPU로 간다 - auto는 그때 disabled + 경고 로그를 남긴다.
    command = _server_command(read("start-llama.bat"))
    assert "-fa auto" in command
    assert "-fa on" not in command


def test_fit_is_off_because_the_script_owns_layers_and_split():
    # common/fit.cpp: -ngl을 사용자가 주면 fit은 매번 "already set by user, abort"를 찍는다.
    command = _server_command(read("start-llama.bat"))
    assert "-ngl 999" in command and "-fit off" in command


def test_kv_cache_type_is_configurable_with_an_f16_default():
    body = read("start-llama.bat")
    assert 'if not defined LLAMA_KV_TYPE set "LLAMA_KV_TYPE=f16"' in body
    assert "-ctk %LLAMA_KV_TYPE% -ctv %LLAMA_KV_TYPE%" in _server_command(body)


def test_prompt_cache_ram_is_passed_only_when_configured():
    body = read("start-llama.bat")
    assert "if defined LLAMA_CACHE_RAM_MIB set" in body
    assert "%CACHE_RAM_ARG%" in _server_command(body)


def test_mtp_speculative_decoding_is_opt_in():
    body = read("start-llama.bat")
    assert 'if "%LLAMA_SPEC_MTP%"=="1" set "SPEC_ARG=--spec-type draft-mtp"' in body
    assert "%SPEC_ARG%" in _server_command(body)
    assert "--spec-type" not in _server_command(body).replace("%SPEC_ARG%", "")


def test_lora_is_loaded_by_a_relative_path_because_the_scale_separator_is_a_colon():
    # b11010 common/arg.cpp --lora-scaled: string_split(item, ':') 후 parts.size()!=2면
    # 거부한다. H:\... 같은 절대경로는 콜론이 하나 더 생겨 기동이 실패한다.
    # start-llama.bat은 번들 루트로 cd 하므로 lora\ 상대경로가 성립한다.
    body = read("start-llama.bat")
    assert 'cd /d "%ROOT%"' in body
    assert 'set LORA_ARG=--lora-scaled "lora\\%LORA_FILE%:%LORA_SCALE%"' in body
    assert "%LORA_ARG%" in _server_command(body)
    assert "%ROOT%lora" not in body.split("set LORA_ARG=", 1)[1].splitlines()[0]


def test_lora_scale_defaults_to_one_and_a_missing_adapter_stops_startup():
    body = read("start-llama.bat")
    assert 'if not defined LORA_SCALE set "LORA_SCALE=1.0"' in body
    assert 'if defined LORA_FILE if not exist "%ROOT%lora\\%LORA_FILE%"' in body


def test_start_llama_arguments_still_include_the_original_contract():
    command = _server_command(read("start-llama.bat"))
    for required in ("--jinja", "--host 127.0.0.1", "-ngl 999", "--parallel 1", "-sm layer",
                     "%TS_ARG%", "%MMPROJ_ARG%"):
        assert required in command, required


# --- config.env 검증 ------------------------------------------------------------


def test_new_keys_accept_good_values():
    text = "\n".join([
        'set "LLAMA_KV_TYPE=q8_0"',
        'set "LLAMA_CACHE_RAM_MIB=32768"',
        'set "LLAMA_SPEC_MTP=1"',
        'set "LORA_FILE=pi-sessions-2026w38.gguf"',
        'set "LORA_SCALE=0.5"',
    ])
    values, problems = config_parse.parse_text(text)
    assert problems == []
    assert values["LORA_SCALE"] == "0.5"


@pytest.mark.parametrize(
    "line",
    [
        'set "LLAMA_KV_TYPE=q4_0"',
        'set "LLAMA_KV_TYPE=bf16"',
        'set "LLAMA_CACHE_RAM_MIB=lots"',
        'set "LLAMA_SPEC_MTP=yes"',
        'set "LORA_FILE=..\\secret.gguf"',
        'set "LORA_FILE=sub\\a.gguf"',
        'set "LORA_FILE=a.gguf:2"',
        'set "LORA_FILE=a.gguf,b.gguf"',
        'set "LORA_FILE=adapter.bin"',
        # ')'는 start-llama.bat if 블록 안 echo에서 블록을 조기에 닫는다(opencode 리뷰).
        'set "LORA_FILE=adapter).gguf"',
        'set "LORA_FILE=a b.gguf"',
        'set "LORA_SCALE=-1"',
        'set "LORA_SCALE=abc"',
        'set "LORA_SCALE=3"',
    ],
)
def test_new_keys_refuse_bad_values(line):
    _, problems = config_parse.parse_text(line + "\n")
    assert problems, line


def test_config_example_documents_and_parses_the_new_keys():
    example = read("config.env.example")
    for key in ("LLAMA_KV_TYPE", "LLAMA_CACHE_RAM_MIB", "LLAMA_SPEC_MTP", "LORA_FILE", "LORA_SCALE"):
        assert f'set "{key}=' in example, key
    values, problems = config_parse.parse_text(example)
    assert problems == []
    assert values["LLAMA_SPEC_MTP"] == "0", "MTP는 리허설 A/B 전까지 기본 꺼짐"
    assert values["LORA_FILE"] == "", "어댑터 없이 기본 모델로 뜨는 것이 기본값"


def test_config_example_context_comment_matches_the_hybrid_model_math():
    # qwen35: 전체 어텐션 16층만 KV를 가진다(스펙 6절). 2*4*256*ctx*2B*16.
    example = read("config.env.example")
    ctx = int(re.search(r'set "LLAMA_CTX=(\d+)"', example).group(1))
    gib = 2 * 4 * 256 * ctx * 2 * 16 / 2**30
    assert f"{gib:.1f} GiB" in example


# --- lora\ 는 대상 PC에서 생기는 가변 영역 ----------------------------------------


def test_lora_directory_is_outside_the_manifest(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "x.exe").write_bytes(b"x")
    doc = manifest.build(tmp_path, staged_at="2026-09-17T00:00:00Z", target="T")
    (tmp_path / "lora").mkdir()
    (tmp_path / "lora" / "adapter.gguf").write_bytes(b"trained on site")
    assert manifest.verify(tmp_path, doc) == []


def test_only_the_served_alias_gets_the_server_context():
    document = json.loads(TEMPLATE)
    extra = dict(document["providers"]["local"]["models"][0])
    extra["id"] = "other-model"
    extra["contextWindow"] = 8192
    extra["maxTokens"] = 4096
    document["providers"]["local"]["models"].append(extra)
    body, problems = render_models_json.render(json.dumps(document), "8080", "qwen3.8-27b", ctx="65536")
    assert problems == []
    models = {m["id"]: m for m in json.loads(body)["providers"]["local"]["models"]}
    assert models["qwen3.8-27b"]["contextWindow"] == 65536
    assert models["other-model"]["contextWindow"] == 8192


def test_the_missing_adapter_message_quotes_the_path_inside_the_block():
    body = read("start-llama.bat")
    assert 'echo [FAIL] "%ROOT%lora\\%LORA_FILE%" not found' in body


# --- L0 비가중치 학습: /retro 프롬프트 템플릿 -------------------------------------
# 합의 L0: 가중치를 건드리지 않고 세션 교훈을 사람이 검토해 AGENTS.md에 누적한다.
# 템플릿은 번들 루트(해시 범위 안)에 두고 --prompt-template로 직접 읽힌다 -
# home\agent로 복사하지 않으므로 동기화 로직이 없다.


def test_start_pi_loads_the_retro_template_from_the_bundle_root():
    body = read("start-pi.bat")
    assert 'if exist "%ROOT%pi-prompts\\retro.md" set PROMPT_ARG=--prompt-template "%ROOT%pi-prompts\\retro.md"' in body
    launch = next(line for line in body.splitlines() if line.startswith('"%ROOT%bin\\pi\\pi.exe" --offline'))
    assert "%PROMPT_ARG%" in launch
    assert launch.rstrip().endswith("%*"), "사용자 인자는 여전히 마지막에 그대로 넘어간다"


def test_retro_template_proposes_only_and_points_at_the_lora_folder():
    text = (WIN / "pi-prompts" / "retro.md").read_text(encoding="utf-8")
    assert text.startswith("---\ndescription:")
    assert "파일을 쓰거나 고치지 마라" in text
    assert "$ARGUMENTS" in text
    assert "C:\\pi_agent\\lora\\approved.txt" in text


def test_retro_template_is_staged_at_the_bundle_root_unchanged():
    staged = ROOT / "pi-prompts" / "retro.md"
    assert staged.read_bytes() == (WIN / "pi-prompts" / "retro.md").read_bytes()


def test_export_sessions_wrapper_passes_fixed_paths_and_the_exit_code():
    body = read("export-sessions.bat")
    call = next(line for line in body.splitlines() if line.startswith("%PYTHON_CMD%") and "export_sessions.py" in line)
    assert '--sessions-dir "%ROOT%home\\agent\\sessions"' in call
    assert '--approved "%ROOT%lora\\approved.txt"' in call
    assert '--out "%ROOT%lora\\train.jsonl"' in call
    assert call.rstrip().endswith("%*")
    after = body[body.index(call) + len(call):]
    assert after.splitlines()[1].strip() == "exit /b %errorlevel%"
    assert body.index("PYTHONUTF8=1") < body.index(call)


# --- 반입하지 않는 모델은 config.env로도 고를 수 없다 --------------------------------
# agy 리뷰(2026-09-17): manifest.EXCLUDED_PATHS의 모델은 해시되지 않는다. 반입 매체에
# 함께 복사돼 MODEL_FILE로 지정되면 무결성 검사 없이 실행된다. 문서가 아니라 코드가 막는다.


@pytest.mark.parametrize(
    "line",
    [
        'set "MODEL_FILE=Qwen3.8-27B-Q8_0.gguf"',
        'set "MODEL_FILE=Qwen3.8-27B-Uncensored-GGUF\\Qwen3.8-27B-Uncensored-Q8_0.gguf"',
        'set "MODEL_FILE=DeepSeek-R1-0528-Qwen3-8B-GGUF/DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf"',
        'set "MMPROJ_FILE=Qwen3.8-27B-Uncensored-GGUF\\mmproj-Qwen3.8-27B-Uncensored-F16.gguf"',
    ],
)
def test_models_outside_the_manifest_cannot_be_selected(line):
    _, problems = config_parse.parse_text(line + "\n")
    assert any("매니페스트" in problem for problem in problems), line


@pytest.mark.parametrize("name", ["Qwen3.8-27B-Q6_K.gguf", "Qwen3.8-27B-Q4_K_M.gguf"])
def test_shipped_models_can_be_selected(name):
    _, problems = config_parse.parse_text(f'set "MODEL_FILE={name}"\n')
    assert problems == []
