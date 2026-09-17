import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import assets


def test_catalog_pins_the_two_verified_hashes():
    pi = assets.CATALOG["pi"]
    assert pi.name == "pi-windows-x64.zip"
    assert pi.sha256 == "002fa95b90d521245b9985d8f168caebc237ad56e7e30b319807dee1b2e17e1c"
    assert pi.bytes == 45009021
    cuda = assets.CATALOG["llama-cuda"]
    assert cuda.name == "llama-b11010-bin-win-cuda-12.4-x64.zip"
    assert cuda.sha256 == "f66167619958a9c94a3ff43f0f847a83399716f40d70c2c7c9ed097d0a11c280"


def test_catalog_carries_cudart_vulkan_and_cpu():
    for key in ("llama-cudart", "llama-vulkan", "llama-cpu"):
        assert key in assets.CATALOG
        assert assets.CATALOG[key].url.startswith("https://github.com/ggml-org/llama.cpp/releases/download/b11010/")
    for key in ("llama-cudart", "llama-vulkan", "llama-cpu"):
        assert assets.CATALOG[key].sha256 is not None and len(assets.CATALOG[key].sha256) == 64
        assert assets.CATALOG[key].bytes and assets.CATALOG[key].bytes > 0


def test_no_catalog_entry_may_reference_cuda_13():
    for key, asset in assets.CATALOG.items():
        assert assets.forbidden_reason(asset.name) is None, key
        assert assets.forbidden_reason(asset.url) is None, key


def test_cuda_13_is_refused_by_name_and_by_url():
    assert assets.forbidden_reason("llama-b11010-bin-win-cuda-13.3-x64.zip") is not None
    assert assets.forbidden_reason("https://example/cudart-llama-bin-win-cuda-13.4-arm64.zip") is not None


def test_verify_downloaded_detects_size_and_hash_drift(tmp_path):
    asset = assets.Asset(name="x.zip", url="https://example/x.zip", sha256="0" * 64, bytes=4)
    path = tmp_path / "x.zip"
    path.write_bytes(b"abcd")
    problems = assets.verify_downloaded(path, asset)
    assert any("sha256" in p for p in problems)

    short = assets.Asset(name="x.zip", url="https://example/x.zip", sha256="0" * 64, bytes=99)
    problems = assets.verify_downloaded(path, short)
    assert any("bytes" in p for p in problems)


def test_verify_downloaded_is_quiet_when_the_file_matches(tmp_path):
    import hashlib

    payload = b"abcd"
    path = tmp_path / "x.zip"
    path.write_bytes(payload)
    asset = assets.Asset(
        name="x.zip",
        url="https://example/x.zip",
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
    )
    assert assets.verify_downloaded(path, asset) == []


def test_catalog_pins_the_bundled_python_runtime():
    # 관리자 권한도 네트워크도 없는 곳에서 파이썬이 없거나 Microsoft Store의
    # 앱 실행 별칭 스텁이 잡히면 복구가 불가능하다. 번들이 자기 파이썬을 들고 간다.
    python = assets.CATALOG["python-embed"]
    assert python.name == "python-3.12.10-embed-amd64.zip"
    assert python.url == (
        "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
    )
    assert python.sha256 == "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
    assert python.bytes == 11133606


def test_every_catalog_entry_is_pinned():
    for key, asset in assets.CATALOG.items():
        assert asset.sha256 and len(asset.sha256) == 64, key
        assert asset.bytes and asset.bytes > 0, key
