import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import stage


def test_plan_targets_maps_every_catalog_entry_to_its_own_directory():
    targets = stage.plan_targets()
    assert targets["pi"] == ("bin/pi", "")
    assert targets["llama-cuda"] == ("bin/llama-cuda", "cuda")
    assert targets["llama-cudart"] == ("bin/llama-cuda", "")
    assert targets["llama-vulkan"] == ("bin/llama-vulkan", "vulkan")
    assert targets["llama-cpu"] == ("bin/llama-cpu", "cpu")


def test_manifest_command_writes_a_document_and_verifies_it(tmp_path, capsys):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pi.exe").write_bytes(b"x")
    code = stage.main(["manifest", "--root", str(tmp_path), "--target", "H:\\model\\pi_agent"])
    assert code == 0
    document = json.loads((tmp_path / "STAGING_MANIFEST.json").read_text())
    assert document["totals"]["files"] == 1

    code = stage.main(["verify", "--root", str(tmp_path)])
    assert code == 0


def test_verify_command_fails_after_tampering(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pi.exe").write_bytes(b"x")
    stage.main(["manifest", "--root", str(tmp_path), "--target", "T"])
    (tmp_path / "bin" / "pi.exe").write_bytes(b"tampered")
    assert stage.main(["verify", "--root", str(tmp_path)]) == 1


def test_fetch_refuses_a_catalog_entry_without_a_pinned_hash(monkeypatch, tmp_path):
    import assets

    unpinned = assets.Asset(name="x.zip", url="https://example/x.zip", sha256=None, bytes=None)
    monkeypatch.setitem(assets.CATALOG, "llama-vulkan", unpinned)
    code = stage.main(["fetch", "--root", str(tmp_path), "--cache", str(tmp_path / ".cache")])
    assert code == 1


def test_layout_refuses_to_extract_when_cache_file_is_tampered(tmp_path):
    import zipfile
    import assets

    # Create a synthetic zip file with correct metadata
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()
    zip_path = cache_dir / "pi-windows-x64.zip"

    # Create a minimal zip file
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("test.txt", "test content")

    # Tamper with the zip file - change its content
    zip_path.write_bytes(b"TAMPERED")

    # layout should verify cache files and reject the tampered one
    code = stage.main(["layout", "--root", str(tmp_path), "--cache", str(cache_dir), "--skip-vc-runtime"])
    assert code == 1


def test_layout_requires_vc_source_or_skip_flag(tmp_path, capsys):
    import zipfile
    import assets
    import unittest.mock as mock

    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()

    # Create minimal zip files for each asset
    for key, asset in {
        "pi": "pi-windows-x64.zip",
        "llama-cuda": f"llama-b10470-bin-win-cuda-12.4-x64.zip",
        "llama-cudart": "cudart-llama-bin-win-cuda-12.4-x64.zip",
        "llama-vulkan": f"llama-b10470-bin-win-vulkan-x64.zip",
        "llama-cpu": f"llama-b10470-bin-win-cpu-x64.zip",
    }.items():
        z = zipfile.ZipFile(cache_dir / asset, "w")
        z.close()

    # Mock assets with pinned hashes/bytes to pass verification
    pinned_catalog = {
        k: assets.Asset(
            name=v,
            url="http://example.com/" + v,
            sha256="0000000000000000000000000000000000000000000000000000000000000000",
            bytes=22,  # minimum zip file size
        )
        for k, v in {
            "pi": "pi-windows-x64.zip",
            "llama-cuda": f"llama-b10470-bin-win-cuda-12.4-x64.zip",
            "llama-cudart": "cudart-llama-bin-win-cuda-12.4-x64.zip",
            "llama-vulkan": f"llama-b10470-bin-win-vulkan-x64.zip",
            "llama-cpu": f"llama-b10470-bin-win-cpu-x64.zip",
        }.items()
    }

    with mock.patch("assets.CATALOG", pinned_catalog):
        with mock.patch("assets.verify_downloaded", return_value=[]):
            with mock.patch("layout.extract"):
                with mock.patch("layout.check_backend_dir", return_value=[]):
                    # Subtest 1: Without --vc-source and without --skip-vc-runtime, should fail
                    # and the failure reason should mention vc-source or skip-vc-runtime
                    code = stage.main(["layout", "--root", str(tmp_path), "--cache", str(cache_dir)])
                    assert code == 1
                    captured = capsys.readouterr()
                    stderr_text = captured.err
                    assert "--vc-source" in stderr_text or "--skip-vc-runtime" in stderr_text, \
                        f"vc-source gate message not found in stderr: {stderr_text}"

                    # Subtest 2: With --skip-vc-runtime, should succeed
                    code = stage.main(["layout", "--root", str(tmp_path), "--cache", str(cache_dir), "--skip-vc-runtime"])
                    assert code == 0


def test_manifest_and_verify_require_root_argument(tmp_path):
    import pytest

    # Commands should require --root to be specified
    with pytest.raises(SystemExit):
        stage.main(["manifest", "--target", "H:\\model\\pi_agent"])
