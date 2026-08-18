"""반입 대상 상류 자산의 카탈로그와 획득.

CUDA 13 계열은 Pascal PTX가 없어 1080 Ti에서 동작하지 않는다. 이름이나 URL
어디에 나타나든 거부한다 — 파일명만 보면 최신이라 고르기 쉬운 함정이다.
"""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

from manifest import sha256_of

_LLAMA_TAG = "b10470"
_LLAMA_BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{_LLAMA_TAG}/"
_PI_BASE = "https://github.com/earendil-works/pi/releases/download/v0.84.2/"
_FORBIDDEN_TOKENS = ("cuda-13", "cuda_13", "cuda-14", "cuda_14")


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    sha256: str | None
    bytes: int | None


def _llama(name: str, sha256: str | None = None, size: int | None = None) -> Asset:
    return Asset(name=name, url=_LLAMA_BASE + name, sha256=sha256, bytes=size)


CATALOG: dict[str, Asset] = {
    "pi": Asset(
        name="pi-windows-x64.zip",
        url=_PI_BASE + "pi-windows-x64.zip",
        sha256="741fc1ae1afecb573ac2888e011188ff446b3940f4aabe1583f60bf55be8a3d0",
        bytes=45470989,
    ),
    "llama-cuda": _llama(
        f"llama-{_LLAMA_TAG}-bin-win-cuda-12.4-x64.zip",
        "e6f3fa9790ab7684ded44ade774dc94742ddb99e4b0abaf1603dab4f3d0803d3",
        250799028,
    ),
    "llama-cudart": _llama(
        "cudart-llama-bin-win-cuda-12.4-x64.zip",
        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
        391443627,
    ),
    "llama-vulkan": _llama(
        f"llama-{_LLAMA_TAG}-bin-win-vulkan-x64.zip",
        "2e89637b30e0e2f90d4ed486118e8642f60625b1dbebb9ba3a30bc4100306fc9",
        34815594,
    ),
    "llama-cpu": _llama(
        f"llama-{_LLAMA_TAG}-bin-win-cpu-x64.zip",
        "a31f1f317813ae7e044be183e0a20b90e78a80c0e97ee11a8b32a014eccd5043",
        18470203,
    ),
}


def forbidden_reason(name_or_url: str) -> str | None:
    lowered = name_or_url.lower()
    for token in _FORBIDDEN_TOKENS:
        if token in lowered:
            return f"{token} 계열은 Pascal(compute 6.1)용 PTX를 담지 않는다"
    return None


def verify_downloaded(path: Path, asset: Asset) -> list[str]:
    problems: list[str] = []
    if not path.is_file():
        return [f"missing file: {path}"]
    if asset.bytes is not None and path.stat().st_size != asset.bytes:
        problems.append(f"bytes mismatch: {path.name} has {path.stat().st_size}, expected {asset.bytes}")
    if asset.sha256 is not None:
        actual = sha256_of(path)
        if actual != asset.sha256:
            problems.append(f"sha256 mismatch: {path.name} is {actual}, expected {asset.sha256}")
    return problems


def download(asset: Asset, into: Path) -> Path:
    reason = forbidden_reason(asset.url)
    if reason:
        raise ValueError(f"거부된 자산 {asset.name}: {reason}")
    into.mkdir(parents=True, exist_ok=True)
    destination = into / asset.name
    if destination.exists() and not verify_downloaded(destination, asset):
        return destination
    with urllib.request.urlopen(asset.url) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    return destination
