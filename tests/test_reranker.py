"""2026-10-02 리랭커 서버 연결(bge-reranker-v2-m3 → LightRAG 질의)의 계약.

근거: tasks/pi-agent-reranker/artifacts/consensus.md(pane 합의 1~11), llama.cpp b11010
소스, 번들 휠 lightrag-hku 1.5.7. GPU가 없는 PC에서 만든 설정이라 여기서 보는 것은 값이
어떻게 흐르는지와 기동 전 확인 도구의 판정뿐이다 - 실제 기동은 리허설 11-24다.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "win"
sys.path.insert(0, str(ROOT / "tools"))
import config_parse
import kg_budget
import rerank_probe


def read(name: str) -> str:
    return (WIN / name).read_text(encoding="ascii")


def parse(lines: str):
    return config_parse.parse_text("@echo off\n" + lines)


def template_env() -> dict[str, str]:
    return kg_budget.parse_env_file((WIN / "kg" / "lightrag.env").read_text(encoding="utf-8"))


# --- 합의 2·8: 설정 키와 포트 ------------------------------------------------------


def test_config_example_carries_the_reranker_defaults():
    values, problems = config_parse.parse_text((WIN / "config.env.example").read_text(encoding="ascii"))
    assert problems == []
    assert values["RERANK_MODEL_FILE"] == "bge-reranker-v2-m3-Q8_0.gguf"
    assert values["RERANK_PORT"] == "8082" and values["RERANK_GPU"] == "2"


def test_reranker_values_reach_the_sanitized_cmd():
    values, problems = parse('set "RERANK_PORT=9000"\nset "RERANK_GPU=1"\n')
    assert problems == []
    text = config_parse.render_cmd(values)
    assert 'set "RERANK_PORT=9000"' in text and 'set "RERANK_GPU=1"' in text


@pytest.mark.parametrize(
    "lines",
    [
        'set "RERANK_PORT=0"\n',
        'set "RERANK_PORT=abc"\n',
        'set "RERANK_GPU=8"\n',
        'set "RERANK_MODEL_FILE=..\\x.gguf"\n',
    ],
)
def test_bad_reranker_values_are_refused_with_a_diagnosis(lines):
    _, problems = parse(lines)
    assert problems and all("행" in problem for problem in problems)


@pytest.mark.parametrize(
    "lines,clash",
    [
        ('set "LLAMA_PORT=8080"\nset "EMBED_PORT=8081"\nset "RERANK_PORT=8082"\n', None),
        ("", None),  # 전부 생략 = 기본값 8080/8081/8082
        ('set "RERANK_PORT=8080"\n', "RERANK_PORT"),  # 생략된 LLAMA_PORT의 기본값과 충돌
        ('set "RERANK_PORT=8081"\n', "RERANK_PORT"),  # 생략된 EMBED_PORT의 기본값과 충돌
        ('set "LLAMA_PORT=8082"\n', "RERANK_PORT"),  # 생략된 RERANK_PORT의 기본값과 충돌
        ('set "LLAMA_PORT=8081"\n', "EMBED_PORT"),  # 기존 검사가 놓치던 경우
        ('set "LLAMA_PORT=08081"\nset "EMBED_PORT=8081"\n', "EMBED_PORT"),  # 문자열로는 다르다
        ('set "EMBED_PORT="\nset "RERANK_PORT=8081"\n', "RERANK_PORT"),  # 비운 값도 기본값으로 뜬다
        ('set "EMBED_PORT=9000"\nset "RERANK_PORT=9000"\n', "RERANK_PORT"),
    ],
)
def test_the_three_server_ports_must_all_differ(lines, clash):
    _, problems = parse(lines)
    if clash is None:
        assert problems == []
    else:
        assert any(clash in problem and "다툰다" in problem for problem in problems)


# --- 합의 1·4: start-rerank.bat ---------------------------------------------------


def test_reranker_server_uses_the_bundle_llama_and_rank_pooling():
    text = read("start-rerank.bat")
    assert 'set "LLAMA_DIR=%ROOT%bin\\llama-cuda"' in text
    launch = text[text.index('"%LLAMA_DIR%\\llama-server.exe" ^'):text.index("exit /b %errorlevel%")]
    assert "--reranking" in launch and "--pooling rank" in launch
    assert "--pooling cls" not in launch and "--embeddings" not in launch
    assert "--alias bge-reranker-v2-m3" in launch
    assert "--host 127.0.0.1" in launch and "--port %RERANK_PORT%" in launch
    assert '-m "%ROOT%models\\%RERANK_MODEL_FILE%"' in launch
    arguments = dict(pair.split() for pair in ("-c 8192", "-b 8192", "-ub 8192", "-np 1"))
    for flag, value in arguments.items():
        assert f"  {flag} {value}" in launch
    assert 'set "CUDA_VISIBLE_DEVICES=%RERANK_GPU%"' in text
    assert 'if not exist "%ROOT%models\\%RERANK_MODEL_FILE%" (' in text


def test_reranker_bat_quotes_every_path_echoed_inside_a_block():
    # 괄호가 든 설치 경로·파일 이름이 if ( ) 블록 안에서 따옴표 없이 펼쳐지면 ')'가 블록을 닫는다.
    depth = checked = 0
    for line in read("start-rerank.bat").splitlines():
        stripped = line.strip()
        if depth and stripped.startswith("echo") and "%" in stripped:
            for variable in ("%LLAMA_DIR%", "%ROOT%"):
                if variable in stripped:
                    assert f'"{variable}' in stripped, stripped
                    checked += 1
        if stripped.endswith("("):
            depth += 1
        elif stripped == ")":
            depth -= 1
    assert checked >= 2  # llama-server.exe 부재, 모델 파일 부재


def test_reranker_bat_defaults_match_the_config_defaults():
    text = read("start-rerank.bat")
    assert 'if not defined RERANK_MODEL_FILE set "RERANK_MODEL_FILE=bge-reranker-v2-m3-Q8_0.gguf"' in text
    assert f'if not defined RERANK_PORT set "RERANK_PORT={config_parse.SERVER_PORT_DEFAULTS["RERANK_PORT"]}"' in text
    assert f'if not defined RERANK_PORT set "RERANK_PORT={config_parse.SERVER_PORT_DEFAULTS["RERANK_PORT"]}"' in read("start-lightrag.bat")
    assert f'if not defined EMBED_PORT set "EMBED_PORT={config_parse.SERVER_PORT_DEFAULTS["EMBED_PORT"]}"' in read("start-embedding.bat")
    assert f'if not defined LLAMA_PORT set "LLAMA_PORT={config_parse.SERVER_PORT_DEFAULTS["LLAMA_PORT"]}"' in read("start-llama.bat")


def test_reranker_bat_reads_config_through_the_sanitizing_parser():
    text = read("start-rerank.bat")
    assert 'tools\\config_parse.py" --config "%ROOT%config.env"' in text
    assert text.index("call :load_config") < text.index("if not defined RERANK_PORT")


def test_reranker_bat_is_ascii_crlf():
    raw = (WIN / "start-rerank.bat").read_bytes()
    assert all(byte < 128 for byte in raw)
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


# --- 합의 5·6: LightRAG 템플릿 -----------------------------------------------------


def test_lightrag_template_turns_rerank_on_against_the_local_server():
    env = template_env()
    assert env["RERANK_BINDING"] == "cohere"
    assert env["RERANK_BINDING_HOST"] == "http://127.0.0.1:8082/v1/rerank"
    assert env["RERANK_MODEL"] == "bge-reranker-v2-m3"
    assert f'--alias {env["RERANK_MODEL"]} ' in read("start-rerank.bat")
    assert env["RERANK_BINDING_API_KEY"]
    assert env["RERANK_BY_DEFAULT"] == "true"
    assert env["RERANK_ENABLE_CHUNKING"] == "false"


def test_lightrag_template_does_not_filter_by_score_before_it_is_measured():
    env = template_env()
    assert float(env["MIN_RERANK_SCORE"]) == 0.0
    assert env["MAX_ASYNC_RERANK"] == "1"
    assert int(env["RERANK_TIMEOUT"]) == 120


# --- 합의 7: start-lightrag.bat이 리랭커를 확인한다 ---------------------------------


def test_start_lightrag_injects_the_rerank_host_and_probes_before_launch():
    text = read("start-lightrag.bat")
    assert 'set "RERANK_BINDING_HOST=http://127.0.0.1:%RERANK_PORT%/v1/rerank"' in text
    probe = (
        '"%KG_PY%" "%ROOT%tools\\rerank_probe.py" --env-file "%KG_WORK%\\.env" '
        "--llama-port %LLAMA_PORT% --embed-port %EMBED_PORT%"
    )
    assert probe in text
    launch = text.rindex('"%KG_HOME%\\venv\\Scripts\\lightrag-server.exe"')
    assert text.index('set "RERANK_BINDING_HOST=') < text.index(probe) < launch
    after = text[text.index(probe):launch]
    assert "if errorlevel 1 (" in after and "exit /b 3" in after
    # 바인딩 자체는 운영자의 .env가 정한다 - bat이 프로세스 환경으로 덮으면 끌 수 없다.
    assert 'set "RERANK_BINDING=' not in text


GOOD = {"results": [{"index": 1, "relevance_score": -3.2}, {"index": 0, "relevance_score": 7.5}]}
ON = "RERANK_BINDING=cohere\nRERANK_MODEL=bge-reranker-v2-m3\nRERANK_BINDING_API_KEY=k\n"
HOST = "http://127.0.0.1:8082/v1/rerank"


def probe(tmp_path, env_text, answer=GOOD, process=None, ports=("8080", "8081")):
    env = tmp_path / ".env"
    env.write_text(env_text, encoding="utf-8")
    calls = []

    def post(url, payload, api_key):
        calls.append((url, payload, api_key))
        if isinstance(answer, Exception):
            raise answer
        return answer

    code = rerank_probe.main(
        ["--env-file", str(env), "--llama-port", ports[0], "--embed-port", ports[1]],
        post=post,
        process={"RERANK_BINDING_HOST": HOST} if process is None else process,
    )
    return code, calls


def test_probe_sends_what_lightrag_will_send_and_accepts_unnormalized_scores(tmp_path):
    code, calls = probe(tmp_path, ON)
    assert code == 0
    (url, payload, api_key), = calls
    assert url == HOST and api_key == "k"
    assert payload["model"] == "bge-reranker-v2-m3"
    assert len(payload["documents"]) == 2 and payload["top_n"] == 2 and payload["query"]


def test_probe_passes_the_shipped_template(tmp_path):
    text = (WIN / "kg" / "lightrag.env").read_text(encoding="utf-8")
    code, calls = probe(tmp_path, text)
    assert code == 0 and calls[0][0] == HOST


@pytest.mark.parametrize(
    "answer",
    [
        ConnectionRefusedError("down"),
        {"results": []},
        {"results": [{"index": 0, "relevance_score": 1.0}]},
        {"results": [{"index": 0, "relevance_score": 1.0}, {"index": 0, "relevance_score": 0.5}]},
        {"results": [{"index": 0, "relevance_score": 1.0}, {"index": 2, "relevance_score": 0.5}]},
        {"results": [{"index": True, "relevance_score": 1.0}, {"index": 0, "relevance_score": 0.5}]},
        {"results": [{"index": 0, "relevance_score": True}, {"index": 1, "relevance_score": 0.5}]},
        {"results": [{"index": 0, "relevance_score": float("nan")}, {"index": 1, "relevance_score": 0.5}]},
        {"results": [{"index": 0, "relevance_score": "0.9"}, {"index": 1, "relevance_score": 0.5}]},
        {"results": [{"index": 0}, {"index": 1}]},
        {"results": "no"},
        {"data": [{"embedding": [0.1]}]},  # 임베딩 서버의 답
        {"error": {"message": "This server does not support reranking"}},
        ["not", "an object"],
    ],
)
def test_probe_refuses_anything_but_a_reranker_answer(tmp_path, capsys, answer):
    code, _ = probe(tmp_path, ON, answer=answer)
    assert code == 1
    assert "RERANK_BINDING=null" in capsys.readouterr().err  # 끄는 법을 알려 준다


def test_probe_skips_the_request_when_rerank_is_off(tmp_path, capsys):
    for text in ("RERANK_BINDING=null\n", ""):
        code, calls = probe(tmp_path, text)
        assert code == 0 and calls == []
    assert "null" in capsys.readouterr().out


@pytest.mark.parametrize("binding", ["jina", "aliyun", "Cohere", "none", ""])
def test_probe_refuses_bindings_the_bundle_never_checked(tmp_path, capsys, binding):
    code, calls = probe(tmp_path, f"RERANK_BINDING={binding}\n")
    assert code == 1 and calls == []
    assert "cohere" in capsys.readouterr().err


def test_probe_keeps_an_empty_model_and_falls_back_to_the_cohere_key_like_lightrag(tmp_path):
    text = "RERANK_BINDING=cohere\nRERANK_MODEL=\n"
    code, calls = probe(tmp_path, text, process={"RERANK_BINDING_HOST": HOST, "COHERE_API_KEY": "fallback"})
    assert code == 0
    assert calls[0][1]["model"] == "" and calls[0][2] == "fallback"
    code, calls = probe(tmp_path, "RERANK_BINDING=cohere\n")
    assert calls[0][1]["model"] == rerank_probe.COHERE_MODEL and calls[0][2] is None


def test_probe_ignores_proxy_settings_for_the_local_server(tmp_path, monkeypatch):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(self.path)
            data = json.dumps(GOOD).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")  # 아무도 듣지 않는 포트
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    try:
        body = rerank_probe.default_post(f"http://127.0.0.1:{server.server_port}/v1/rerank", {"q": 1}, None)
    finally:
        server.shutdown()
        server.server_close()
    assert body == GOOD and seen == ["/v1/rerank"]


def test_probe_refuses_cohere_without_a_host(tmp_path, capsys):
    code, calls = probe(tmp_path, ON, process={})
    assert code == 1 and calls == []
    assert "RERANK_BINDING_HOST" in capsys.readouterr().err


def test_process_environment_wins_over_the_env_file(tmp_path):
    text = ON + "RERANK_BINDING_HOST=http://127.0.0.1:1/old\n"
    code, calls = probe(tmp_path, text, process={"RERANK_BINDING_HOST": HOST, "RERANK_MODEL": "other", "UNRELATED": "x"})
    assert code == 0
    assert calls[0][0] == HOST and calls[0][1]["model"] == "other"
    off, calls = probe(tmp_path, text, process={"RERANK_BINDING": "null"})
    assert off == 0 and calls == []


@pytest.mark.parametrize(
    "env_text,name",
    [
        ("PORT=8080\n", "LLAMA_PORT"),
        ("PORT=8081\n", "EMBED_PORT"),
        ("PORT=08081\n", "EMBED_PORT"),
        (ON + "PORT=8082\n", "RERANK_BINDING_HOST"),
        ("PORT=abc\n", "정수"),
    ],
)
def test_lightrag_port_cannot_equal_a_server_port(tmp_path, capsys, env_text, name):
    code, calls = probe(tmp_path, env_text)
    assert code == 1 and calls == []
    assert name in capsys.readouterr().err


def test_lightrag_port_check_runs_even_when_rerank_is_off(tmp_path):
    assert probe(tmp_path, "RERANK_BINDING=null\nPORT=8080\n")[0] == 1
    # 꺼져 있으면 쓰지 않는 리랭커 포트와는 겹쳐도 된다.
    assert probe(tmp_path, "RERANK_BINDING=null\nPORT=8082\n")[0] == 0
    # LightRAG 기본 포트 9621도 본다.
    assert probe(tmp_path, "RERANK_BINDING=null\n", ports=("9621", "8081"))[0] == 1


def test_probe_reports_an_unreadable_env_file(tmp_path, capsys):
    code = rerank_probe.main(["--env-file", str(tmp_path / "missing"), "--llama-port", "8080", "--embed-port", "8081"], process={})
    assert code == 1 and "읽지 못했다" in capsys.readouterr().err


def test_probe_talks_http_like_the_cohere_binding(tmp_path):
    """default_post가 실제 HTTP로 JSON을 보내고 받는다(llama-server의 /v1/rerank 자리에 모의 서버)."""
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = json.dumps(GOOD).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/rerank"
        env = tmp_path / ".env"
        env.write_text(ON, encoding="utf-8")
        code = rerank_probe.main(
            ["--env-file", str(env), "--llama-port", "8080", "--embed-port", "8081"],
            process={"RERANK_BINDING_HOST": url},
        )
    finally:
        server.shutdown()
        server.server_close()
    assert code == 0
    assert seen["path"] == "/v1/rerank" and seen["auth"] == "Bearer k"
    assert seen["body"]["top_n"] == 2 and seen["body"]["model"] == "bge-reranker-v2-m3"


def test_probe_fails_fast_when_nothing_listens(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text(ON, encoding="utf-8")
    code = rerank_probe.main(
        ["--env-file", str(env), "--llama-port", "8080", "--embed-port", "8081"],
        process={"RERANK_BINDING_HOST": "http://127.0.0.1:9/v1/rerank"},
    )
    assert code == 1 and "start-rerank.bat" in capsys.readouterr().err
    assert rerank_probe.PROBE_TIMEOUT == 10
