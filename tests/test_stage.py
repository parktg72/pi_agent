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
