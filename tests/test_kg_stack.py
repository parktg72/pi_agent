"""2026-09-22 KG 정렬(폐쇄망지식그래프 → pi_agent)의 계약.

근거: tasks/pi-agent-kg-align/artifacts/consensus.md(pane 합의 1~13)와 llama.cpp b11010
소스. 문자열이 있다는 것만이 아니라 값이 실제로 어떻게 흐르는지를 본다.
"""
import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "win"
sys.path.insert(0, str(ROOT / "tools"))
import config_parse
import manifest
import server_profile
import stage

KG_SOURCE = ROOT / "폐쇄망지식그래프"


def read(name: str) -> str:
    return (WIN / name).read_text(encoding="ascii")


def example_values() -> dict[str, str]:
    values, problems = config_parse.parse_text((WIN / "config.env.example").read_text(encoding="ascii"))
    assert problems == []
    return values


def parse(lines: str):
    return config_parse.parse_text("@echo off\n" + lines)


# --- 합의 2·3·6: start-llama.bat 서버 인자 ---------------------------------------


def test_flash_attention_comes_from_the_key_with_an_auto_default():
    text = read("start-llama.bat")
    assert "-fa %LLAMA_FLASH_ATTN%" in text
    assert 'if not defined LLAMA_FLASH_ATTN set "LLAMA_FLASH_ATTN=auto"' in text
    assert "-fa auto" not in text and "-fa on" not in text


def test_flash_attention_on_is_refused_because_it_skips_the_device_probe():
    _, problems = parse('set "LLAMA_FLASH_ATTN=on"\n')
    assert problems
    for mode in ("auto", "off"):
        _, problems = parse(f'set "LLAMA_FLASH_ATTN={mode}"\n')
        assert problems == []


def test_kv_type_now_sets_k_only_and_v_stays_f16():
    text = read("start-llama.bat")
    assert "-ctk %LLAMA_KV_TYPE%" in text
    assert "-ctv f16" in text
    assert "-ctv %LLAMA_KV_TYPE%" not in text
    assert 'if not defined LLAMA_KV_TYPE set "LLAMA_KV_TYPE=q8_0"' in text


def test_batch_ubatch_and_mmap_follow_the_kg_guide():
    text = read("start-llama.bat")
    assert "-b 1024" in text
    assert "-ub %LLAMA_UBATCH%" in text
    assert 'if not defined LLAMA_UBATCH set "LLAMA_UBATCH=256"' in text
    assert "--no-mmap" in text


@pytest.mark.parametrize("value,ok", [("256", True), ("1024", True), ("128", True), ("2048", False), ("300", False)])
def test_ubatch_cannot_exceed_the_fixed_logical_batch(value, ok):
    _, problems = parse(f'set "LLAMA_UBATCH={value}"\n')
    assert (problems == []) is ok


def test_config_example_carries_the_kg_aligned_defaults():
    values = example_values()
    assert values["MODEL_FILE"] == "Qwen3.8-27B-UD-Q5_K_M.gguf"
    assert values["LLAMA_FLASH_ATTN"] == "auto"
    assert values["LLAMA_KV_TYPE"] == "q8_0"
    assert values["LLAMA_UBATCH"] == "256"
    assert values["GPU_TENSOR_SPLIT"] == "10,11,8"
    assert values["CHAT_TEMPLATE_FILE"] == "qwen38-c3cf9e34.jinja"
    assert values["KG_CTX"] == "32768" and values["KG_PARALLEL"] == "4"
    assert values["EMBED_MODEL_FILE"] == "bge-m3-FP16.gguf"
    assert values["EMBED_PORT"] == "8081" and values["EMBED_GPU"] == "2"


# --- 합의 5: kg 프로파일 --------------------------------------------------------


def test_kg_profile_switches_context_and_slots_and_drops_the_projector():
    text = read("start-llama.bat")
    assert 'if /I "%~1"=="kg" set "PROFILE=kg"' in text
    assert 'if "%PROFILE%"=="kg" set "CTX=%KG_CTX%"' in text
    assert 'if "%PROFILE%"=="kg" set "PARALLEL=%KG_PARALLEL%"' in text
    assert 'if "%PROFILE%"=="kg" set "MMPROJ_ARG="' in text
    assert "-c %CTX%" in text and "--parallel %PARALLEL%" in text
    assert 'set "PARALLEL=1"' in text and 'set "CTX=%LLAMA_CTX%"' in text


def test_an_unknown_profile_argument_stops_startup():
    text = read("start-llama.bat")
    assert 'if not "%~1"=="" if /I not "%~1"=="kg" (' in text


@pytest.mark.parametrize(
    "lines,ok",
    [
        ('set "KG_CTX=32768"\nset "KG_PARALLEL=4"\n', True),
        ('set "KG_CTX=32768"\nset "KG_PARALLEL=3"\n', False),  # 나누어떨어지지 않는다
        ('set "KG_CTX=16384"\nset "KG_PARALLEL=4"\n', False),  # 슬롯 4096 < 8192(lightrag.env 가정)
        ('set "KG_CTX=16384"\nset "KG_PARALLEL=2"\n', True),  # 슬롯 8192
        ('set "KG_PARALLEL=5"\n', False),
    ],
)
def test_kg_slot_size_is_checked(lines, ok):
    _, problems = parse(lines)
    assert (problems == []) is ok


def test_the_embedding_port_cannot_equal_the_llm_port():
    _, problems = parse('set "LLAMA_PORT=8080"\nset "EMBED_PORT=8080"\n')
    assert any("EMBED_PORT" in problem for problem in problems)


# --- 합의 9: LoRA는 검증된 기반 모델에서만 -----------------------------------------


def test_lora_is_refused_on_the_unverified_q5_base():
    _, problems = parse('set "MODEL_FILE=Qwen3.8-27B-UD-Q5_K_M.gguf"\nset "LORA_FILE=a.gguf"\n')
    assert any("LORA_FILE" in problem for problem in problems)


def test_lora_is_allowed_on_the_verified_q6_base():
    _, problems = parse('set "MODEL_FILE=Qwen3.8-27B-Q6_K.gguf"\nset "LORA_FILE=a.gguf"\n')
    assert problems == []


# --- 합의 4·8: 모델과 매니페스트 --------------------------------------------------


def test_the_kg_source_folder_is_outside_the_manifest_and_git():
    assert "폐쇄망지식그래프" in manifest.EXCLUDED_ROOTS
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/폐쇄망지식그래프/" in ignore
    assert "packages_win/kg/" in ignore


@pytest.mark.parametrize(
    "name",
    ["Qwen3.8-27B-UD-Q5_K_M.gguf", "Qwen3.8-27B-Q6_K.gguf", "Qwen3.8-27B-Q4_K_M.gguf", "bge-m3-FP16.gguf"],
)
def test_shipped_models_stay_inside_the_manifest(name):
    assert f"models/{name}" not in manifest.EXCLUDED_PATHS
    _, problems = parse(f'set "MODEL_FILE={name}"\n')
    assert problems == []


def _gguf_with_architecture(path: Path, architecture: str) -> None:
    # GGUF v3 헤더 + 메타데이터 1개(general.architecture). 텐서 0개.
    import struct

    key = b"general.architecture"
    value = architecture.encode()
    body = b"GGUF" + struct.pack("<IQQ", 3, 0, 1)
    body += struct.pack("<Q", len(key)) + key + struct.pack("<I", 8) + struct.pack("<Q", len(value)) + value
    path.write_bytes(body)


def test_model_check_skips_a_bge_embedding_model_but_not_a_disguised_chat_model(tmp_path, capsys):
    models = tmp_path / "models"
    models.mkdir()
    _gguf_with_architecture(models / "bge-m3-FP16.gguf", "bert")
    _gguf_with_architecture(models / "bge-chat.gguf", "qwen35")
    code = stage._model_check(tmp_path)
    out = capsys.readouterr()
    assert "[skip] bge-m3-FP16.gguf" in out.out
    assert code == 1  # bge-chat.gguf는 채팅 모델로 검사돼 템플릿이 없어 실패
    assert "bge-chat.gguf" in out.out + out.err


# --- 합의 11: 템플릿 고정 --------------------------------------------------------


def test_the_pinned_template_is_the_original_qwen38_template():
    pinned = (WIN / "chat-templates" / "qwen38-c3cf9e34.jinja").read_bytes()
    assert hashlib.sha256(pinned).hexdigest().startswith("c3cf9e34")
    assert pinned == (ROOT / "tests" / "fixtures" / "qwen38_chat_template.jinja").read_bytes()


def test_start_llama_passes_the_template_and_stops_if_it_is_missing():
    text = read("start-llama.bat")
    assert 'set TEMPLATE_ARG=--chat-template-file "%ROOT%chat-templates\\%CHAT_TEMPLATE_FILE%"' in text
    assert "%TEMPLATE_ARG%" in text.split('"%LLAMA_DIR%\\llama-server.exe"', 1)[1]
    assert 'if defined CHAT_TEMPLATE_FILE if not exist "%ROOT%chat-templates\\%CHAT_TEMPLATE_FILE%" (' in text


@pytest.mark.parametrize("value", ["../x.jinja", "a b.jinja", "x.txt", "sub\\x.jinja"])
def test_template_file_names_are_restricted(value):
    _, problems = parse(f'set "CHAT_TEMPLATE_FILE={value}"\n')
    assert problems


# --- 합의 13: Pi는 kg 서버에 붙지 않는다 --------------------------------------------


def _props(slots=1, n_ctx=63488, template="T"):
    return {"total_slots": slots, "default_generation_settings": {"n_ctx": n_ctx}, "chat_template": template}


def test_the_pi_profile_server_is_accepted():
    assert server_profile.check_props(_props(), 63488, "T") == []
    assert server_profile.check_props(_props(template="T\r\n"), 63488, "T\n") == []


def test_a_kg_profile_server_is_refused():
    problems = server_profile.check_props(_props(slots=4, n_ctx=8192), 63488, None)
    assert any("슬롯이 4개" in problem for problem in problems)
    assert any("8192" in problem for problem in problems)


def test_a_wrong_template_or_missing_fields_are_refused():
    assert server_profile.check_props(_props(template="other"), 63488, "T")
    assert server_profile.check_props({}, 63488, None)
    assert server_profile.check_props({"total_slots": 1, "default_generation_settings": {}}, 63488, None)


def test_an_unreachable_server_is_refused(tmp_path):
    def boom(url):
        raise OSError("connection refused")

    assert server_profile.main(["--base-url", "http://127.0.0.1:1", "--ctx", "63488"], fetch=boom) == 1


def test_main_reads_the_template_and_asks_props(tmp_path):
    template = tmp_path / "t.jinja"
    template.write_text("T", encoding="utf-8")
    seen = []

    def fetch(url):
        seen.append(url)
        return _props()

    assert server_profile.main(["--base-url", "http://h:1", "--ctx", "63488", "--template-file", str(template)], fetch=fetch) == 0
    assert seen == ["http://h:1/props"]


def test_start_pi_checks_the_server_profile_before_pi_starts():
    text = read("start-pi.bat")
    wait = text.index("tools\\wait_model.py")
    check = text.index("tools\\server_profile.py")
    launch = text.index('"%ROOT%bin\\pi\\pi.exe" --offline')
    unset = text.index('set "LLAMA_BASE_URL="', wait)
    assert wait < check < unset < launch
    assert '--ctx "%LLAMA_CTX%"' in text
    assert "exit /b 11" in text


# --- 합의 7: 임베딩·설치·LightRAG 스크립트 -----------------------------------------


def test_embedding_server_uses_the_bundle_llama_and_bge_settings():
    text = read("start-embedding.bat")
    assert 'set "LLAMA_DIR=%ROOT%bin\\llama-cuda"' in text
    assert "--embeddings" in text and "--pooling cls" in text
    assert "--host 127.0.0.1" in text
    assert 'set "CUDA_VISIBLE_DEVICES=%EMBED_GPU%"' in text
    ctx = int(re.search(r"-c (\d+)", text).group(1))
    ub = int(re.search(r"-ub (\d+)", text).group(1))
    assert ub >= ctx == 8192


@pytest.mark.parametrize("name", ["start-embedding.bat", "start-lightrag.bat", "install-kg.bat", "start-rerank.bat"])
def test_kg_batch_files_quote_paths_echoed_inside_a_block(name):
    # 설치 경로나 파일 이름에 괄호가 있으면, if ( ) 블록 안에서 따옴표 없이 펼쳐진 ')'가 블록을
    # 닫아 진단 대신 구문 오류가 난다(tasks/pi-agent-reranker codex R3). PYTHON_CMD는 값에
    # 따옴표가 들어 있을 수 있어 감싸지 않는다 - config_parse가 그 값의 문자를 따로 막는다.
    depth = checked = 0
    for number, line in enumerate(read(name).splitlines(), start=1):
        stripped = line.strip()
        if depth and stripped.startswith("echo"):
            unquoted = re.sub(r'"[^"]*"', "", stripped).replace("%PYTHON_CMD%", "")
            assert "%" not in unquoted, f"{name}:{number}: {stripped}"
            checked += "%" in stripped
        if stripped.endswith("(") and not stripped.startswith(")"):
            depth += 1
        elif stripped == ")":
            depth -= 1
    assert depth == 0 and checked >= 2


def test_install_kg_is_offline_isolated_and_fails_loudly():
    text = read("install-kg.bat")
    assert '--no-index --find-links="%KG_WHEELS%"' in text
    assert 'set "KG_VENV=%KG_HOME%\\venv"' in text and 'set "KG_HOME=%ROOT%home\\kg"' in text
    assert "packages_win\\py312" not in text.replace("rem ", "", 0).split("rem Every step")[1]
    assert "-m pip check" in text
    for code in ("exit /b 5", "exit /b 4", "exit /b 2"):
        assert code in text
    assert "setx" not in text.lower()


def test_start_lightrag_sets_the_tokenizer_cache_for_the_process_only():
    text = read("start-lightrag.bat")
    assert 'set "TIKTOKEN_CACHE_DIR=%KG_HOME%\\tiktoken_cache"' in text
    assert "setx" not in text.lower()
    assert 'if not exist "%KG_WORK%\\.env" copy /y "%ROOT%kg\\lightrag.env"' in text


@pytest.mark.parametrize("name", ["start-embedding.bat", "install-kg.bat", "start-lightrag.bat"])
def test_new_batch_files_are_ascii_crlf(name):
    raw = (WIN / name).read_bytes()
    assert all(byte < 128 for byte in raw)
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


# --- 합의 12: LightRAG 예산이 슬롯 안에 든다 -----------------------------------------


def _env() -> dict[str, str]:
    values = {}
    for line in (WIN / "kg" / "lightrag.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def test_every_lightrag_request_fits_one_kg_slot_with_margin():
    env = _env()
    slot = int(example_values()["KG_CTX"]) // int(example_values()["KG_PARALLEL"])
    ceiling = slot * 0.85  # tiktoken과 Qwen 토크나이저 수 차이 여유
    out = int(env["OPENAI_LLM_MAX_TOKENS"])
    assert int(env["MAX_EXTRACT_INPUT_TOKENS"]) + out <= ceiling
    assert int(env["SUMMARY_CONTEXT_SIZE"]) + out <= ceiling
    assert int(env["MAX_TOTAL_TOKENS"]) + out <= ceiling
    assert int(env["MAX_ENTITY_TOKENS"]) + int(env["MAX_RELATION_TOKENS"]) < int(env["MAX_TOTAL_TOKENS"])
    assert int(env["CHUNK_SIZE"]) < int(env["MAX_EXTRACT_INPUT_TOKENS"])


def test_lightrag_talks_only_to_local_servers_and_turns_thinking_off():
    env = _env()
    assert env["HOST"] == "127.0.0.1"
    assert env["LLM_BINDING_HOST"] == "http://127.0.0.1:8080/v1"
    assert env["EMBEDDING_BINDING_HOST"] == "http://127.0.0.1:8081/v1"
    assert env["EMBEDDING_DIM"] == "1024"
    assert env["LLM_MODEL"] == example_values()["MODEL_ALIAS"]
    assert '"enable_thinking": false' in env["OPENAI_LLM_EXTRA_BODY"]


# --- 합의 7: graphify 스킬은 네트워크 경로가 없는 사본이다 -------------------------------

NETWORK_MARKERS = re.compile(
    r"https?://|pip install|uv tool (install|run)|--neo4j-push|--falkordb-push|--push |--whisper-model|yt-dlp|git clone|sponsors"
)


def test_the_graphify_skill_has_no_network_paths():
    skill = WIN / "pi-skills" / "graphify"
    files = [skill / "SKILL.md", *sorted((skill / "references").glob("*.md"))]
    assert (skill / "SKILL.md").is_file()
    assert not (skill / "references" / "github-and-merge.md").exists()
    assert not (skill / "references" / "transcribe.md").exists()
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            # MCP 설정 예시 문단의 uv 언급은 설명일 뿐 실행 지시가 아니다.
            if "claude_desktop_config.json" in line:
                continue
            assert not NETWORK_MARKERS.search(line), f"{path.name}:{number}: {line[:120]}"


def test_the_graphify_skill_runs_from_the_bundle_venv():
    text = (WIN / "pi-skills" / "graphify" / "SKILL.md").read_text(encoding="utf-8")
    assert "home/kg/venv/Scripts/python.exe" in text
    assert text.startswith("---\nname: graphify\n")


def test_start_pi_loads_the_graphify_skill_from_the_bundle_root():
    text = read("start-pi.bat")
    assert 'if exist "%ROOT%pi-skills\\graphify\\SKILL.md" set SKILL_ARG=--skill "%ROOT%pi-skills\\graphify"' in text
    assert "%SKILL_ARG%" in text.split('"%ROOT%bin\\pi\\pi.exe" --offline', 1)[1]


@pytest.mark.skipif(not KG_SOURCE.is_dir(), reason="폐쇄망지식그래프 원본은 gitignore - 스테이징 PC에만 있다")
def test_the_sanitized_skill_is_reproducible_from_the_source(tmp_path):
    import sanitize_graphify_skill

    wheel = ROOT / "packages_win" / "kg" / "wheelhouse" / "graphifyy-0.9.65-py3-none-any.whl"
    extra = ["--license-wheel", str(wheel)] if wheel.is_file() else []
    assert sanitize_graphify_skill.main(["--src", str(KG_SOURCE / "05_skills" / "graphify"), "--dst", str(tmp_path / "g"), *extra]) == 0
    shipped = WIN / "pi-skills" / "graphify"
    for path in sorted(shipped.rglob("*.md")):
        assert path.read_bytes() == (tmp_path / "g" / path.relative_to(shipped)).read_bytes(), path.name


# --- codex R4 반영 ------------------------------------------------------------------

import graphify_offline_html


def test_graph_html_cdn_scripts_are_rewritten_to_local_copies():
    html = (
        '<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"\n'
        '        integrity="sha384-x" crossorigin="anonymous"></script>'
    )
    out, needed, leftover = graphify_offline_html.rewrite(html)
    assert out == '<script src="vis-network-9.1.6.min.js"></script>'
    assert needed == {"vis-network-9.1.6.min.js"} and leftover == []


def test_an_unknown_external_script_is_reported_not_passed_silently(tmp_path):
    page = tmp_path / "graph.html"
    page.write_text('<script src="https://example.com/x.js"></script>', encoding="utf-8")
    problems = graphify_offline_html.process([tmp_path], web=tmp_path / "web")
    assert any("모르는 외부 참조" in problem for problem in problems)


def test_a_local_copy_with_the_wrong_hash_is_refused(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "d3-7.9.0.min.js").write_text("not d3", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "tree.html").write_text('<script src="https://d3js.org/d3.v7.min.js"></script>', encoding="utf-8")
    problems = graphify_offline_html.process([out], web=web)
    assert any("sha256" in problem for problem in problems)
    assert not (out / "d3-7.9.0.min.js").exists()
    # 검증이 실패하면 HTML을 건드리지 않는다 - 외부 URL이 남아야 다음 실행이 다시 검사한다.
    assert "https://d3js.org/d3.v7.min.js" in (out / "tree.html").read_text(encoding="utf-8")


@pytest.mark.skipif(not graphify_offline_html.WEB.is_dir(), reason="packages_win/kg/web은 gitignore - 스테이징 PC에만 있다")
def test_a_rerun_rechecks_and_restores_local_copies(tmp_path):
    page = tmp_path / "graph.html"
    page.write_text('<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>', encoding="utf-8")
    assert graphify_offline_html.process([tmp_path]) == []
    copy = tmp_path / "vis-network-9.1.6.min.js"
    assert copy.is_file()
    copy.write_text("tampered", encoding="utf-8")
    assert graphify_offline_html.process([tmp_path]) == []
    expected = graphify_offline_html.KNOWN["https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"][1]
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == expected


@pytest.mark.skipif(not graphify_offline_html.WEB.is_dir(), reason="packages_win/kg/web은 gitignore - 스테이징 PC에만 있다")
def test_the_bundled_web_copies_match_the_pinned_hashes():
    for name, sha in graphify_offline_html.KNOWN.values():
        assert hashlib.sha256((graphify_offline_html.WEB / name).read_bytes()).hexdigest() == sha, name


def test_the_skill_runs_the_offline_html_step_and_quotes_the_interpreter():
    skill = WIN / "pi-skills" / "graphify"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert "tools/graphify_offline_html.py" in text
    for path in [skill / "SKILL.md", *sorted((skill / "references").glob("*.md"))]:
        body = path.read_text(encoding="utf-8")
        assert not re.search(r'(^|[^"])\$\(cat graphify-out/\.graphify_python\)', body, re.MULTILINE), path.name


def test_start_pi_passes_the_bundle_root_and_leaves_path_alone():
    text = read("start-pi.bat")
    assert 'set "PI_AGENT_ROOT=%ROOT:\\=/%"' in text
    assert 'set "PI_AGENT_ROOT=%PI_AGENT_ROOT:~0,-1%"' in text
    # PATH의 다른 graphify와 섞이지 않게 스킬이 번들 venv를 직접 부른다(codex R5 #2).
    assert 'set "PATH=' not in text


def test_the_skill_never_calls_a_bare_graphify_command():
    import sanitize_graphify_skill

    skill = WIN / "pi-skills" / "graphify"
    bare = re.compile(r"(^|[ `:])graphify (query|export|path|explain|update|cluster-only|hook|claude|benchmark)\\b")
    for path in [skill / "SKILL.md", *sorted((skill / "references").glob("*.md"))]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.startswith("description:"):
                continue
            rest = line.replace(sanitize_graphify_skill.BUNDLE_GRAPHIFY, "")
            assert not bare.search(rest), f"{path.name}:{number}: {line[:100]}"



def test_start_lightrag_passes_config_values_and_checks_every_step():
    text = read("start-lightrag.bat")
    assert 'set "LLM_BINDING_HOST=http://127.0.0.1:%LLAMA_PORT%/v1"' in text
    assert 'set "EMBEDDING_BINDING_HOST=http://127.0.0.1:%EMBED_PORT%/v1"' in text
    assert 'set "LLM_MODEL=%MODEL_ALIAS%"' in text
    assert '"%KG_PY%" "%ROOT%tools\\kg_budget.py" --env-file "%KG_WORK%\\.env"' in text
    assert 'if not exist "%KG_WORK%\\.env" (' in text
    launch = text.rindex('"%KG_HOME%\\venv\\Scripts\\lightrag-server.exe"')
    for step in ("kg_budget.py", 'cd /d "%KG_WORK%"', 'set "TIKTOKEN_CACHE_DIR='):
        assert text.index(step) < launch, step


import kg_budget


def test_the_shipped_lightrag_env_fits_the_kg_slot():
    env = kg_budget.parse_env_file((WIN / "kg" / "lightrag.env").read_text(encoding="utf-8"))
    assert kg_budget.check_budget(env, config_parse.KG_MIN_SLOT_CTX) == []


def test_library_defaults_or_a_missing_output_cap_are_refused():
    assert any("OPENAI_LLM_MAX_TOKENS" in p for p in kg_budget.check_budget({}, 8192))
    problems = kg_budget.check_budget({"OPENAI_LLM_MAX_TOKENS": "2500"}, 8192)
    assert any("SUMMARY_CONTEXT_SIZE" in p for p in problems)  # 기본 12000
    assert any("MAX_TOTAL_TOKENS" in p for p in problems)  # 기본 30000


def test_process_environment_wins_over_the_env_file_like_lightrag():
    env_file = {"OPENAI_LLM_MAX_TOKENS": "2500", "SUMMARY_CONTEXT_SIZE": "4000"}
    merged = kg_budget.effective(env_file, {"SUMMARY_CONTEXT_SIZE": "12000", "UNRELATED": "x"})
    assert merged["SUMMARY_CONTEXT_SIZE"] == "12000" and "UNRELATED" not in merged


def test_kg_budget_ignores_proxy_settings_for_the_local_server(tmp_path, monkeypatch):
    # urllib은 http_proxy를 따르지만 LightRAG의 LLM 호출은 로컬 서버로 바로 간다.
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps(_props(4, 8192)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for key in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(key, "http://127.0.0.1:9")  # 아무도 듣지 않는 포트
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    env = tmp_path / ".env"
    env.write_text((WIN / "kg" / "lightrag.env").read_text(encoding="utf-8"), encoding="utf-8")
    try:
        code = kg_budget.main(["--env-file", str(env), "--base-url", f"http://127.0.0.1:{server.server_port}"], process={})
    finally:
        server.shutdown()
        server.server_close()
    assert code == 0


def test_start_lightrag_keeps_local_calls_off_the_proxy_before_any_check():
    # 기동 확인(kg_budget·rerank_probe)은 프록시를 무시한다. LLM·임베딩 호출(httpx)은 따른다 -
    # NO_PROXY에 루프백이 없으면 확인만 통과한다(tasks/pi-agent-reranker codex R6).
    text = read("start-lightrag.bat")
    line = 'if defined NO_PROXY (set "NO_PROXY=%NO_PROXY%,127.0.0.1,localhost") else set "NO_PROXY=127.0.0.1,localhost"'
    assert line in text
    assert text.index("setlocal") < text.index(line) < text.index("kg_budget.py") < text.rindex("lightrag-server.exe")
    assert "setx" not in text.lower()


def test_kg_budget_reads_the_slot_from_the_running_server(tmp_path):
    env = tmp_path / ".env"
    env.write_text((WIN / "kg" / "lightrag.env").read_text(encoding="utf-8"), encoding="utf-8")
    ok = kg_budget.main(["--env-file", str(env), "--base-url", "http://h:1"], fetch=lambda u: _props(4, 8192), process={})
    small = kg_budget.main(["--env-file", str(env), "--base-url", "http://h:1"], fetch=lambda u: _props(4, 4096), process={})

    def down(url):
        raise OSError("refused")

    gone = kg_budget.main(["--env-file", str(env), "--base-url", "http://h:1"], fetch=down, process={})
    assert (ok, small, gone) == (0, 1, 1)


# --- codex R6 반영 ------------------------------------------------------------------


def test_the_fallback_env_parser_follows_dotenv_on_export_and_duplicates():
    env = kg_budget.parse_env_file("SUMMARY_CONTEXT_SIZE=4000\nexport SUMMARY_CONTEXT_SIZE=12000\n")
    assert env["SUMMARY_CONTEXT_SIZE"] == "12000"
    merged = kg_budget.effective({**kg_budget.parse_env_file((WIN / "kg" / "lightrag.env").read_text(encoding="utf-8")), **env}, {})
    assert any("SUMMARY_CONTEXT_SIZE" in p for p in kg_budget.check_budget(merged, 8192))


@pytest.mark.parametrize("key", ["MAX_EXTRACT_INPUT_TOKENS", "OPENAI_LLM_MAX_TOKENS", "MAX_TOTAL_TOKENS", "CHUNK_SIZE"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_zero_or_negative_caps_are_refused_because_zero_can_mean_unlimited(key, value):
    env = kg_budget.parse_env_file((WIN / "kg" / "lightrag.env").read_text(encoding="utf-8"))
    env[key] = value
    assert any(key in p and "양수" in p for p in kg_budget.check_budget(env, 8192))


def test_the_skill_interpreter_guard_uses_only_the_bundle_venv():
    text = (WIN / "pi-skills" / "graphify" / "SKILL.md").read_text(encoding="utf-8")
    guard = text[text.index("## Interpreter guard for subcommands"):]
    guard = guard[: guard.index("\n## ", 5)]
    assert 'BUNDLE_PY="${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe"' in guard
    assert "which graphify" not in guard and 'PYTHON="python3"' not in guard
    assert '!= "$BUNDLE_EXE"' in guard  # 다른 인터프리터를 가리키는 기존 기록도 다시 쓴다


def test_env_reading_uses_dotenv_with_lightrags_override_false(tmp_path, monkeypatch):
    # dotenv_values()는 ${VAR} 확장에서 .env를 우선한다(override=True) - LightRAG와 다르다(codex R7 #1).
    import types

    seen = {}

    class FakeDotEnv:
        def __init__(self, path, **kwargs):
            seen.update(kwargs)

        def dict(self):
            return {"SUMMARY_CONTEXT_SIZE": "12000", "EMPTY": None}

    main = types.ModuleType("dotenv.main")
    main.DotEnv = FakeDotEnv
    package = types.ModuleType("dotenv")
    package.main = main
    monkeypatch.setitem(sys.modules, "dotenv", package)
    monkeypatch.setitem(sys.modules, "dotenv.main", main)
    env = tmp_path / ".env"
    env.write_text("X=1\n", encoding="utf-8")
    assert kg_budget.read_env_file(env) == {"SUMMARY_CONTEXT_SIZE": "12000"}
    assert seen.get("override") is False and seen.get("interpolate") is True



def test_the_modified_graphify_skill_ships_its_apache_license_and_notice():
    skill = WIN / "pi-skills" / "graphify"
    assert "Apache License" in (skill / "LICENSE").read_text(encoding="utf-8")
    assert (skill / "NOTICE").is_file()
    assert "graphify" in (ROOT / "NOTICE").read_text(encoding="utf-8").lower()
