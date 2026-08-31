"""config.env 파싱이 실제로 무엇을 거부하는지 본다.

문자열 검사로는 이번 지적이 재발한다. 여기서는 값을 넣어 보고 결과를 단언한다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import config_parse

GOOD = """@echo off
rem a comment
set "LLAMA_BACKEND=cuda"
set "LLAMA_PORT=18080"
set "MODEL_ALIAS=qwen3.8-27b"
set "PI_MODEL_ID=local/qwen3.8-27b"
set "GPU_TENSOR_SPLIT="
"""


def test_a_clean_config_yields_its_values():
    values, problems = config_parse.parse_text(GOOD)
    assert problems == []
    assert values["LLAMA_PORT"] == "18080"
    assert values["MODEL_ALIAS"] == "qwen3.8-27b"
    assert values["GPU_TENSOR_SPLIT"] == ""


@pytest.mark.parametrize(
    "value",
    [
        "C:\\models & calc.exe",
        "a|b",
        "a>b",
        "a<b",
        "a^b",
        "%PATH%",
        "!DELAYED!",
        'quote"inside',
    ],
)
def test_cmd_metacharacters_in_a_value_are_refused(value):
    # 2026-08-19 실측: & 가 든 값은 뒤가 명령으로 실행되고, %VAR%/!VAR!는
    # 값에서 소실된다. 신뢰된 설정이어도 경로·alias가 조용히 변형된다.
    _, problems = config_parse.parse_text(f'set "MODEL_FILE={value}"\n')
    assert problems, value


def test_an_unknown_key_is_refused_instead_of_ignored():
    _, problems = config_parse.parse_text('set "LLAMA_PORTT=8080"\n')
    assert any("LLAMA_PORTT" in problem for problem in problems)


def test_a_line_that_is_neither_a_comment_nor_a_set_is_refused():
    _, problems = config_parse.parse_text("del /q C:\\pi_agent\n")
    assert problems


@pytest.mark.parametrize(
    "line",
    [
        'set "LLAMA_PORT=0"',
        'set "LLAMA_PORT=70000"',
        'set "LLAMA_PORT=eight"',
        'set "LLAMA_BACKEND=opencl"',
        'set "LLAMA_CTX=0"',
        'set "MODEL_LOAD_TIMEOUT=-5"',
        'set "ALLOW_CPU_DIAGNOSTIC=yes"',
        'set "PI_MODEL_ID=qwen3.8-27b"',
        'set "MODEL_FILE=..\\..\\windows\\system32\\calc.exe"',
        'set "GPU_TENSOR_SPLIT=1;1;1"',
    ],
)
def test_values_of_the_wrong_shape_are_refused(line):
    _, problems = config_parse.parse_text(line + "\n")
    assert problems, line


def test_the_alias_and_the_model_id_must_agree():
    # 이 둘이 어긋나면 서버는 정상인데 Pi만 없는 모델을 요청한다.
    _, problems = config_parse.parse_text(
        'set "MODEL_ALIAS=qwen3.8-27b"\nset "PI_MODEL_ID=local/qwen-other"\n'
    )
    assert any("MODEL_ALIAS" in problem for problem in problems)


def test_the_same_key_twice_is_refused():
    _, problems = config_parse.parse_text('set "LLAMA_PORT=8080"\nset "LLAMA_PORT=9090"\n')
    assert problems


def test_the_sanitized_output_contains_nothing_but_set_statements(tmp_path):
    config = tmp_path / "config.env"
    config.write_text(GOOD, encoding="ascii")
    out = tmp_path / "home" / "agent" / "config.cmd"
    assert config_parse.main(["--config", str(config), "--out", str(out)]) == 0
    lines = [line for line in out.read_text(encoding="ascii").splitlines() if line]
    assert lines[0] == "@echo off"
    for line in lines[1:]:
        assert line.startswith("rem ") or line.startswith('set "'), line
    # 다시 파싱해도 같은 값이 나온다 - 내보낸 파일이 입력 문법의 부분집합이다.
    again, problems = config_parse.parse_text(out.read_text(encoding="ascii"))
    assert problems == []
    assert again == config_parse.parse_text(GOOD)[0]


def test_a_refused_config_writes_no_output_and_returns_nonzero(tmp_path):
    config = tmp_path / "config.env"
    config.write_text('set "MODEL_FILE=x & calc.exe"\n', encoding="ascii")
    out = tmp_path / "config.cmd"
    assert config_parse.main(["--config", str(config), "--out", str(out)]) == 1
    assert not out.exists(), "거부한 설정으로 .cmd를 남기면 다음 실행이 그것을 call한다"


def test_a_missing_config_returns_nonzero(tmp_path):
    assert config_parse.main(
        ["--config", str(tmp_path / "nope.env"), "--out", str(tmp_path / "out.cmd")]
    ) == 1


def test_non_ascii_bytes_are_refused(tmp_path):
    # 비ASCII가 있으면 call되는 .cmd에서 cmd.exe의 줄 오프셋 계산이 어긋난다.
    config = tmp_path / "config.env"
    config.write_bytes('set "MODEL_FILE=모델.gguf"\n'.encode("utf-8"))
    assert config_parse.main(
        ["--config", str(config), "--out", str(tmp_path / "out.cmd")]
    ) == 1


def test_the_write_leaves_no_temporary_file_behind(tmp_path):
    config = tmp_path / "config.env"
    config.write_text(GOOD, encoding="ascii")
    out = tmp_path / "config.cmd"
    assert config_parse.main(["--config", str(config), "--out", str(out)]) == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["config.cmd", "config.env"]


def test_every_key_the_batch_files_read_is_allowed():
    # 허용 목록이 좁아서 정상 설정을 막는 반대 방향의 사고를 잡는다.
    example = (Path(__file__).resolve().parents[1] / "win" / "config.env.example").read_text(
        encoding="ascii"
    )
    values, problems = config_parse.parse_text(example)
    assert problems == []
    assert "LLAMA_BACKEND" in values and "ALLOW_CPU_DIAGNOSTIC" in values


def test_pi_thinking_takes_only_the_levels_the_model_map_offers():
    values, problems = config_parse.parse_text('set "PI_THINKING=medium"')
    assert problems == []
    assert values["PI_THINKING"] == "medium"
    # xhigh는 models.json에서 null로 막아 둔 단계다. Pi는 지원하지 않는 단계를
    # 조용히 당겨 쓰므로, 적은 값과 도는 값이 어긋나기 전에 여기서 멈춘다.
    _, problems = config_parse.parse_text('set "PI_THINKING=xhigh"')
    assert any("PI_THINKING" in problem for problem in problems)
