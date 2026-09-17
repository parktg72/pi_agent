import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import gguf

GGUF_TYPE_UINT32 = 4
GGUF_TYPE_STRING = 8


def _string(value: bytes) -> bytes:
    return struct.pack("<Q", len(value)) + value


def write_gguf(path: Path, pairs: list[tuple[str, int, bytes]]) -> Path:
    body = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", len(pairs))
    for key, value_type, encoded in pairs:
        body += _string(key.encode()) + struct.pack("<I", value_type) + encoded
    path.write_bytes(body)
    return path


def test_read_metadata_returns_requested_string_keys(tmp_path):
    path = write_gguf(
        tmp_path / "m.gguf",
        [
            ("general.architecture", GGUF_TYPE_STRING, _string(b"qwen3moe")),
            ("tokenizer.chat_template", GGUF_TYPE_STRING, _string(b"{% for m in messages %}")),
        ],
    )
    found = gguf.read_metadata(path, ("general.architecture", "tokenizer.chat_template"))
    assert found["general.architecture"] == "qwen3moe"
    assert found["tokenizer.chat_template"].startswith("{% for m in messages %}")


def test_read_metadata_skips_values_it_does_not_need(tmp_path):
    path = write_gguf(
        tmp_path / "m.gguf",
        [
            ("some.count", GGUF_TYPE_UINT32, struct.pack("<I", 7)),
            ("tokenizer.chat_template", GGUF_TYPE_STRING, _string(b"template")),
        ],
    )
    found = gguf.read_metadata(path, ("tokenizer.chat_template",))
    assert found == {"tokenizer.chat_template": "template"}


def test_check_tool_capable_complains_when_the_template_is_absent(tmp_path):
    path = write_gguf(tmp_path / "m.gguf", [("general.architecture", GGUF_TYPE_STRING, _string(b"llama"))])
    problems = gguf.check_tool_capable(path)
    assert any("tokenizer.chat_template" in p for p in problems)


def test_check_tool_capable_is_quiet_on_a_template_that_mentions_tools(tmp_path):
    template = b"{% if tools %}{{ tool_call }}{% endif %}"
    path = write_gguf(tmp_path / "m.gguf", [("tokenizer.chat_template", GGUF_TYPE_STRING, _string(template))])
    assert gguf.check_tool_capable(path) == []


def test_check_tool_capable_flags_a_template_without_any_tool_hook(tmp_path):
    template = b"{% for message in messages %}{{ message.content }}{% endfor %}"
    path = write_gguf(tmp_path / "m.gguf", [("tokenizer.chat_template", GGUF_TYPE_STRING, _string(template))])
    problems = gguf.check_tool_capable(path)
    assert any("tool" in p for p in problems)


def test_rejects_a_file_that_is_not_gguf(tmp_path):
    path = tmp_path / "not.gguf"
    path.write_bytes(b"XXXX" + b"\x00" * 32)
    try:
        gguf.read_metadata(path, ("tokenizer.chat_template",))
    except ValueError as error:
        assert "GGUF" in str(error)
    else:
        raise AssertionError("GGUF가 아닌 파일을 받아들였다")


def test_the_bundled_qwen_template_defaults_to_xhigh_and_takes_three_efforts():
    # models.json의 thinkingLevelMap이 어떤 값을 보내도 되는지는 이 파일이
    # 정한다. 모델이 없는 곳에서는 건너뛰고, 있는 곳에서는 하드코딩한 집합이
    # 여전히 맞는지 실물로 확인한다.
    import pytest

    # 2026-09-17부터 기본 모델은 Q6_K다. 같은 원본을 양자화만 달리한 파일이라 템플릿은 같다.
    model = Path(__file__).resolve().parents[1] / "models" / "Qwen3.8-27B-Q6_K.gguf"
    if not model.is_file():
        pytest.skip("모델 파일이 없는 환경 - 반입 번들에서만 도는 검사")
    template = gguf.read_metadata(model, ("tokenizer.chat_template",)).get(
        "tokenizer.chat_template", ""
    )
    assert "reasoning_effort|default('xhigh')" in template
    assert "not in ('xhigh', 'medium', 'low')" in template
    # enable_thinking is false일 때 <think>를 즉시 닫는 분기가 있어야 off가 산다.
    assert "enable_thinking is defined and enable_thinking is false" in template
