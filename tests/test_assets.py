import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import assets


def test_catalog_pins_the_two_verified_hashes():
    pi = assets.CATALOG["pi"]
    assert pi.name == "pi-windows-x64.zip"
    assert pi.sha256 == "741fc1ae1afecb573ac2888e011188ff446b3940f4aabe1583f60bf55be8a3d0"
    assert pi.bytes == 45470989
    cuda = assets.CATALOG["llama-cuda"]
    assert cuda.name == "llama-b10470-bin-win-cuda-12.4-x64.zip"
    assert cuda.sha256 == "e6f3fa9790ab7684ded44ade774dc94742ddb99e4b0abaf1603dab4f3d0803d3"


def test_catalog_carries_cudart_vulkan_and_cpu():
    for key in ("llama-cudart", "llama-vulkan", "llama-cpu"):
        assert key in assets.CATALOG
        assert assets.CATALOG[key].url.startswith("https://github.com/ggml-org/llama.cpp/releases/download/b10470/")
    for key in ("llama-cudart", "llama-vulkan", "llama-cpu"):
        assert assets.CATALOG[key].sha256 is not None and len(assets.CATALOG[key].sha256) == 64
        assert assets.CATALOG[key].bytes and assets.CATALOG[key].bytes > 0


def test_no_catalog_entry_may_reference_cuda_13():
    for key, asset in assets.CATALOG.items():
        assert assets.forbidden_reason(asset.name) is None, key
        assert assets.forbidden_reason(asset.url) is None, key


def test_cuda_13_is_refused_by_name_and_by_url():
    assert assets.forbidden_reason("llama-b10470-bin-win-cuda-13.3-x64.zip") is not None
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
