import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import manifest


def make_bundle(tmp_path: Path) -> Path:
    (tmp_path / "bin" / "pi").mkdir(parents=True)
    (tmp_path / "bin" / "pi" / "pi.exe").write_bytes(b"binary")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "m.gguf").write_bytes(b"weights")
    (tmp_path / "home" / "agent").mkdir(parents=True)
    (tmp_path / "home" / "agent" / "settings.json").write_text("{}")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "run.log").write_text("noise")
    (tmp_path / "start-pi.bat").write_text("@echo off")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "verify_bundle.py").write_text("# 폐쇄망에서도 실행된다")
    (tmp_path / ".gitignore").write_text("bin/")
    return tmp_path


def test_build_covers_immutable_files_only(tmp_path):
    root = make_bundle(tmp_path)
    (root / ".cache").mkdir()
    (root / ".cache" / "huge.zip").write_bytes(b"downloaded asset, not part of the bundle")
    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="H:\\model\\pi_agent")
    listed = {entry["relative"] for entry in doc["files"]}
    assert listed == {"bin/pi/pi.exe", "models/m.gguf", "start-pi.bat", "tools/verify_bundle.py"}
    assert doc["schema"] == manifest.SCHEMA
    assert doc["totals"]["files"] == 4


def test_verify_is_quiet_on_an_untouched_bundle(tmp_path):
    root = make_bundle(tmp_path)
    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="T")
    assert manifest.verify(root, doc) == []


def test_mutable_areas_may_change_without_breaking_verification(tmp_path):
    root = make_bundle(tmp_path)
    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="T")
    (root / "home" / "agent" / "settings.json").write_text('{"changed": true}')
    (root / "evidence" / "new.log").write_text("first run")
    assert manifest.verify(root, doc) == []


def test_verify_reports_tampering_missing_and_extra_files(tmp_path):
    root = make_bundle(tmp_path)
    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="T")
    (root / "models" / "m.gguf").write_bytes(b"tampere")
    (root / "start-pi.bat").unlink()
    (root / "bin" / "extra.dll").write_bytes(b"x")
    problems = manifest.verify(root, doc)
    assert any("hash mismatch: models/m.gguf" == p for p in problems)
    assert any("missing: start-pi.bat" == p for p in problems)
    assert any("unexpected: bin/extra.dll" == p for p in problems)


def test_manifest_is_json_serialisable_and_sorted(tmp_path):
    root = make_bundle(tmp_path)
    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="T")
    json.dumps(doc)
    relatives = [entry["relative"] for entry in doc["files"]]
    assert relatives == sorted(relatives)


def test_verify_detects_truncation_without_hashing(tmp_path):
    root = make_bundle(tmp_path)
    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="T")
    (root / "models" / "m.gguf").write_bytes(b"weight")
    problems = manifest.verify(root, doc)
    assert any("size mismatch: models/m.gguf" == p for p in problems)
    assert not any("hash mismatch: models/m.gguf" == p for p in problems)


def test_superpowers_sdd_is_excluded_from_manifest(tmp_path):
    root = make_bundle(tmp_path)
    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="H:\\model\\pi_agent")
    listed = {entry["relative"] for entry in doc["files"]}

    (root / ".superpowers" / "sdd" / "plan").mkdir(parents=True)
    (root / ".superpowers" / "sdd" / "plan" / "progress.md").write_text("# Task 8b")
    (root / ".superpowers" / "sdd" / "agent").mkdir(parents=True)
    (root / ".superpowers" / "sdd" / "agent" / "report.txt").write_text("findings")

    doc2 = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="H:\\model\\pi_agent")
    listed2 = {entry["relative"] for entry in doc2["files"]}
    assert listed == listed2, "manifest should not include .superpowers even if new files appear"
    assert doc2["totals"]["files"] == doc["totals"]["files"], "file count should be unchanged"

    problems = manifest.verify(root, doc)
    assert not any(p for p in problems if ".superpowers" in p), "verify should ignore .superpowers changes"
