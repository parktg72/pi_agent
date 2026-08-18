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


def test_pycache_is_excluded_at_every_depth(tmp_path):
    # verify_bundle.py는 import manifest를 먼저 한다. 즉 .pyc를 해시 범위에 넣으면
    # 검사 대상이 검사 도중 다시 쓰인다 — 대상 PC의 파이썬 버전이 다르면
    # unexpected:, 소스 mtime이 바뀌면 hash mismatch:로 확정 실패한다.
    root = make_bundle(tmp_path)
    (root / "tools" / "__pycache__").mkdir()
    (root / "tools" / "__pycache__" / "manifest.cpython-312.pyc").write_bytes(b"bytecode")
    (root / "bin" / "pi" / "vendor" / "pkg" / "__pycache__").mkdir(parents=True)
    (root / "bin" / "pi" / "vendor" / "pkg" / "__pycache__" / "x.cpython-313.pyc").write_bytes(b"deep")
    (root / "bin" / "pi" / "stray.pyc").write_bytes(b"loose bytecode outside __pycache__")

    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="T")
    listed = {entry["relative"] for entry in doc["files"]}
    assert not any("__pycache__" in rel for rel in listed), sorted(listed)
    assert not any(rel.endswith(".pyc") for rel in listed), sorted(listed)
    assert manifest.verify(root, doc) == []


def test_a_pyc_appearing_after_staging_does_not_break_verification(tmp_path):
    root = make_bundle(tmp_path)
    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="T")
    (root / "tools" / "__pycache__").mkdir()
    (root / "tools" / "__pycache__" / "manifest.cpython-314.pyc").write_bytes(b"written on the target PC")
    assert manifest.verify(root, doc) == []


def test_config_env_is_excluded_but_its_example_is_hashed(tmp_path):
    # README와 리허설 절차서가 config.env를 현장에서 채우라고 지시한다.
    # 해시하면 지시를 따른 운영자에게 hash mismatch가 확정적으로 뜬다.
    root = make_bundle(tmp_path)
    (root / "config.env").write_text('set "GPU_TENSOR_SPLIT="\n', encoding="utf-8")
    (root / "config.env.example").write_text('set "GPU_TENSOR_SPLIT="\n', encoding="utf-8")

    doc = manifest.build(root, staged_at="2026-08-18T00:00:00Z", target="T")
    listed = {entry["relative"] for entry in doc["files"]}
    assert "config.env" not in listed
    assert "config.env.example" in listed

    (root / "config.env").write_text('set "GPU_TENSOR_SPLIT=10,11,11"\n', encoding="utf-8")
    assert manifest.verify(root, doc) == [], "현장에서 config.env를 채워도 검사는 조용해야 한다"

    (root / "config.env.example").write_text("tampered\n", encoding="utf-8")
    assert any("config.env.example" in problem for problem in manifest.verify(root, doc))
