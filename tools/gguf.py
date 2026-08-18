"""GGUF 헤더에서 메타데이터 문자열만 읽는다.

가중치는 건드리지 않는다. 목적은 하나 — 반입 전에 tokenizer.chat_template의
존재와 툴 훅 여부를 보는 것이다. 이게 없으면 --jinja를 줘도 툴 호출이
성립하지 않는다.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO

_SCALAR_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_TYPE_STRING = 8
_TYPE_ARRAY = 9


def _read(handle: BinaryIO, fmt: str):
    size = struct.calcsize(fmt)
    return struct.unpack(fmt, handle.read(size))[0]


def _read_string(handle: BinaryIO) -> str:
    length = _read(handle, "<Q")
    return handle.read(length).decode("utf-8", errors="replace")


def _skip_value(handle: BinaryIO, value_type: int) -> None:
    if value_type == _TYPE_STRING:
        handle.seek(_read(handle, "<Q"), 1)
    elif value_type == _TYPE_ARRAY:
        element_type = _read(handle, "<I")
        count = _read(handle, "<Q")
        for _ in range(count):
            _skip_value(handle, element_type)
    else:
        handle.seek(_SCALAR_SIZES[value_type], 1)


def read_metadata(path: Path, keys: tuple[str, ...]) -> dict[str, str]:
    wanted = set(keys)
    found: dict[str, str] = {}
    with path.open("rb") as handle:
        if handle.read(4) != b"GGUF":
            raise ValueError(f"{path.name}은 GGUF 파일이 아니다")
        _read(handle, "<I")  # version
        _read(handle, "<Q")  # tensor count
        kv_count = _read(handle, "<Q")
        for _ in range(kv_count):
            key = _read_string(handle)
            value_type = _read(handle, "<I")
            if key in wanted and value_type == _TYPE_STRING:
                found[key] = _read_string(handle)
            else:
                _skip_value(handle, value_type)
            if len(found) == len(wanted):
                break
    return found


def check_tool_capable(path: Path) -> list[str]:
    metadata = read_metadata(path, ("tokenizer.chat_template",))
    template = metadata.get("tokenizer.chat_template")
    if not template:
        return [f"{path.name}: tokenizer.chat_template이 없다 — 툴 호출이 성립하지 않는다"]
    lowered = template.lower()
    if "tool" not in lowered:
        return [f"{path.name}: chat_template에 tool 훅이 보이지 않는다 — 리허설에서 왕복을 반드시 확인하라"]
    return []
