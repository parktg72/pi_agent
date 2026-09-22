"""의료 용어 체계 슬롯과 pyoxigraph 설치의 계약 (tasks/pi-agent-terminology 합의 1~6)."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "win"
sys.path.insert(0, str(ROOT / "tools"))
import manifest
import terminology_slots as ts

APPROVED = {
    "distributor": "X",
    "release": "2026",
    "acquired_on": "2026-09-23",
    "source_url": "https://example.org",
    "license_terms": "terms.pdf",
    "review_status": "approved",
    "review_scope": "internal analysis only",
    "review_basis": "reviewed terms section 3",
}


def slot_tree(tmp_path: Path, source: str = "umls") -> Path:
    shutil.copytree(ROOT / "terminology", tmp_path / "terminology")
    return tmp_path / "terminology" / source


def put(slot: Path, name: str, body: bytes) -> None:
    path = slot / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def approve(slot: Path) -> None:
    doc = json.loads((slot / "slot.json").read_text(encoding="utf-8"))
    doc.update(APPROVED)
    (slot / "slot.json").write_text(json.dumps(doc), encoding="utf-8")


# --- 합의 1: 자리·git·매니페스트 --------------------------------------------------


@pytest.mark.parametrize("source", ts.SOURCES)
def test_each_slot_has_a_readme_and_an_unreviewed_template(source):
    slot = ROOT / "terminology" / source
    assert (slot / "README.md").is_file()
    example = json.loads((slot / "slot.example.json").read_text(encoding="utf-8"))
    assert example["source"] == source and example["review_status"] == "unreviewed" and example["files"] == []
    assert set(ts.REQUIRED_FIELDS) <= set(example)


def test_dumps_and_filled_records_are_ignored_by_git():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    # 허용 목록: 슬롯 안은 README.md·slot.example.json만 추적(codex R4 #1).
    assert "/terminology/*/*" in ignore and "!/terminology/*/README.md" in ignore and "!/terminology/*/slot.example.json" in ignore
    out = subprocess.run(
        ["git", "check-ignore", "terminology/umls/data/MRCONSO.RRF", "terminology/omop/slot.json", "terminology/umls/README.md"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.split()
    assert "terminology/umls/data/MRCONSO.RRF" in out and "terminology/omop/slot.json" in out
    assert "terminology/umls/README.md" not in out


def test_manifest_hashes_slot_docs_but_not_dumps_or_records(tmp_path):
    assert manifest.TERMINOLOGY_SOURCES == ts.SOURCES
    slot = slot_tree(tmp_path)
    put(slot, "MRCONSO.RRF", b"x")
    (slot / "slot.json").write_text("{}", encoding="utf-8")
    listed = {relative for relative, _ in manifest.iter_immutable_files(tmp_path)}
    assert "terminology/umls/README.md" in listed and "terminology/umls/slot.example.json" in listed
    assert not any(p.startswith("terminology/umls/data") for p in listed)
    assert "terminology/umls/slot.json" not in listed


def test_adding_a_dump_on_site_does_not_break_bundle_verification(tmp_path):
    slot_tree(tmp_path)
    document = manifest.build(tmp_path, staged_at="t", target="x")
    put(tmp_path / "terminology" / "omop", "CONCEPT.csv", b"concept_id\tconcept_name\n")
    assert manifest.verify(tmp_path, document) == []


# --- 합의 3: 상태 -------------------------------------------------------------------


def test_empty_slots_pass(tmp_path):
    slot_tree(tmp_path)
    assert all(ts.check_slot(tmp_path, source) == ("empty", []) for source in ts.SOURCES)
    assert ts.main(["--root", str(tmp_path), "check"]) == 0


def test_data_without_a_record_is_incomplete(tmp_path):
    slot = slot_tree(tmp_path)
    put(slot, "MRCONSO.RRF", b"C0000005|ENG|P|")
    status, problems = ts.check_slot(tmp_path, "umls")
    assert status == "incomplete" and "slot.json" in problems[0]
    assert ts.main(["--root", str(tmp_path), "check"]) == 1


def test_record_then_approve_gives_recorded_not_loadable(tmp_path, capsys):
    slot = slot_tree(tmp_path)
    put(slot, "MRCONSO.RRF", b"C0000005|ENG|P|")
    assert ts.record(tmp_path, "umls")[0]
    doc = json.loads((slot / "slot.json").read_text(encoding="utf-8"))
    assert doc["files"] == [{"path": "MRCONSO.RRF", "bytes": 15, "sha256": hashlib.sha256(b"C0000005|ENG|P|").hexdigest()}]
    assert ts.check_slot(tmp_path, "umls")[0] == "incomplete"  # 아직 unreviewed
    approve(slot)
    assert ts.check_slot(tmp_path, "umls") == ("recorded", [])
    assert ts.main(["--root", str(tmp_path), "check"]) == 0
    assert "적재 가능하다는 뜻이 아니다" in capsys.readouterr().out


def test_rerecording_changed_files_resets_the_review(tmp_path):
    slot = slot_tree(tmp_path)
    put(slot, "a.csv", b"1")
    ts.record(tmp_path, "umls")
    approve(slot)
    put(slot, "a.csv", b"22")
    ok, message = ts.record(tmp_path, "umls")
    assert ok and "unreviewed" in message
    assert json.loads((slot / "slot.json").read_text(encoding="utf-8"))["review_status"] == "unreviewed"


def test_rerecording_identical_files_keeps_the_review(tmp_path):
    slot = slot_tree(tmp_path)
    put(slot, "a.csv", b"1")
    ts.record(tmp_path, "umls")
    approve(slot)
    ts.record(tmp_path, "umls")
    assert ts.check_slot(tmp_path, "umls") == ("recorded", [])


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda slot: put(slot, "a.csv", b"X"), "sha256"),  # 같은 크기, 다른 내용 = 전송 손상
        (lambda slot: put(slot, "a.csv", b"longer"), "크기"),
        (lambda slot: (slot / "data" / "a.csv").unlink(), "없다"),  # 기록된 파일 소실
        (lambda slot: put(slot, "extra.csv", b"e"), "files[]에 없다"),
    ],
)
def test_integrity_problems_make_the_slot_incomplete(tmp_path, mutate, needle):
    slot = slot_tree(tmp_path)
    put(slot, "a.csv", b"1")
    ts.record(tmp_path, "umls")
    approve(slot)
    mutate(slot)
    status, problems = ts.check_slot(tmp_path, "umls")
    assert status == "incomplete" and any(needle in p for p in problems), problems


def test_recorded_files_that_all_vanished_are_not_empty(tmp_path):
    slot = slot_tree(tmp_path)
    put(slot, "a.csv", b"1")
    ts.record(tmp_path, "umls")
    approve(slot)
    shutil.rmtree(slot / "data")
    assert ts.check_slot(tmp_path, "umls")[0] == "incomplete"


@pytest.mark.parametrize("field", ["review_scope", "review_basis", "license_terms", "source_url"])
def test_missing_provenance_or_review_fields_fail(tmp_path, field):
    slot = slot_tree(tmp_path)
    put(slot, "a.csv", b"1")
    ts.record(tmp_path, "umls")
    approve(slot)
    doc = json.loads((slot / "slot.json").read_text(encoding="utf-8"))
    doc[field] = ""
    (slot / "slot.json").write_text(json.dumps(doc), encoding="utf-8")
    status, problems = ts.check_slot(tmp_path, "umls")
    assert status == "incomplete" and any(field in p for p in problems)


@pytest.mark.parametrize("value", ["rejected", "unreviewed", "ok"])
def test_only_approved_review_passes(tmp_path, value):
    slot = slot_tree(tmp_path)
    put(slot, "a.csv", b"1")
    ts.record(tmp_path, "umls")
    approve(slot)
    doc = json.loads((slot / "slot.json").read_text(encoding="utf-8"))
    doc["review_status"] = value
    (slot / "slot.json").write_text(json.dumps(doc), encoding="utf-8")
    assert ts.check_slot(tmp_path, "umls")[0] == "incomplete"


def test_there_is_no_licence_bypass_flag():
    with pytest.raises(SystemExit):
        ts.main(["check", "--accept-license"])


# --- 합의 5: 설치·배치 ----------------------------------------------------------------


def test_install_kg_installs_and_imports_pinned_pyoxigraph_but_not_oxrdflib():
    text = (WIN / "install-kg.bat").read_text(encoding="ascii")
    assert "pyoxigraph==0.5.11" in text and "import lightrag, kuzu, networkx, rdflib, pyoxigraph" in text
    assert "oxrdflib" not in text


@pytest.mark.skipif(not (ROOT / "packages_win" / "kg" / "wheelhouse").is_dir(), reason="휠하우스는 gitignore - 스테이징 PC에만 있다")
def test_the_pyoxigraph_windows_wheel_is_in_the_kg_wheelhouse():
    wheel = ROOT / "packages_win" / "kg" / "wheelhouse" / "pyoxigraph-0.5.11-cp312-cp312-win_amd64.whl"
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == "11bdebeb6d1725a885d39bd2c8d31927c2f375c23375f6a61c85e5802809e217"
    assert not list(wheel.parent.glob("oxrdflib-*.whl"))


def test_check_terminology_bat_uses_goto_so_exit_codes_are_real():
    raw = (WIN / "check-terminology.bat").read_bytes()
    assert all(byte < 128 for byte in raw) and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.decode("ascii")
    assert 'tools\\terminology_slots.py" --root "%ROOT%." check' in text
    assert 'if "%~1"=="" goto :check_all' in text
    # 괄호 블록 안의 exit /b %errorlevel%는 명령 실행 전에 펼쳐진다.
    for block in text.split("(")[1:]:
        assert "%errorlevel%" not in block.split(")")[0]
    assert "/check-terminology.bat" in (ROOT / ".gitignore").read_text(encoding="utf-8")


# --- codex R4 반영 ------------------------------------------------------------------


def test_only_slot_docs_are_tracked_so_strays_cannot_leak_to_git():
    out = subprocess.run(
        ["git", "check-ignore", "terminology/umls/slot.json.bak", "terminology/umls/MRCONSO.RRF", "terminology/stray.txt",
         "terminology/README.md", "terminology/umls/README.md", "terminology/umls/slot.example.json"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.split()
    assert {"terminology/umls/slot.json.bak", "terminology/umls/MRCONSO.RRF", "terminology/stray.txt"} <= set(out)
    assert not {"terminology/README.md", "terminology/umls/README.md", "terminology/umls/slot.example.json"} & set(out)


def test_manifest_never_hashes_stray_files_in_a_slot(tmp_path):
    slot = slot_tree(tmp_path)
    (slot / "MRCONSO.RRF").write_bytes(b"x")
    (slot / "slot.json.bak").write_text("{}", encoding="utf-8")
    (slot / "extra").mkdir()
    (slot / "extra" / "y.csv").write_bytes(b"y")
    listed = {relative for relative, _ in manifest.iter_immutable_files(tmp_path)}
    assert {p for p in listed if p.startswith("terminology/umls/")} == {
        "terminology/umls/README.md", "terminology/umls/slot.example.json"}


def test_stray_files_in_a_slot_make_it_incomplete(tmp_path):
    slot = slot_tree(tmp_path)
    (slot / "MRCONSO.RRF").write_bytes(b"x")
    status, problems = ts.check_slot(tmp_path, "umls")
    assert status == "incomplete" and any("MRCONSO.RRF" in p for p in problems)


def test_a_data_file_instead_of_a_folder_is_not_empty(tmp_path):
    slot = slot_tree(tmp_path)
    (slot / "data").write_bytes(b"dump")
    assert ts.check_slot(tmp_path, "umls")[0] == "incomplete"
    assert ts.record(tmp_path, "umls")[0] is False


@pytest.mark.parametrize("path", ["../outside.csv", "/etc/passwd", "C:x.csv", "a\\b.csv", "./a.csv"])
def test_recorded_paths_must_stay_inside_data(tmp_path, path):
    slot = slot_tree(tmp_path)
    put(slot, "a.csv", b"1")
    ts.record(tmp_path, "umls")
    approve(slot)
    doc = json.loads((slot / "slot.json").read_text(encoding="utf-8"))
    doc["files"].append({"path": path, "bytes": 1, "sha256": "0" * 64})
    (slot / "slot.json").write_text(json.dumps(doc), encoding="utf-8")
    status, problems = ts.check_slot(tmp_path, "umls")
    assert status == "incomplete" and any("상대경로" in p for p in problems)


def test_duplicate_recorded_paths_are_refused(tmp_path):
    slot = slot_tree(tmp_path)
    put(slot, "a.csv", b"1")
    ts.record(tmp_path, "umls")
    approve(slot)
    doc = json.loads((slot / "slot.json").read_text(encoding="utf-8"))
    doc["files"].append(dict(doc["files"][0], sha256="f" * 64))
    (slot / "slot.json").write_text(json.dumps(doc), encoding="utf-8")
    status, problems = ts.check_slot(tmp_path, "umls")
    assert status == "incomplete" and any("두 번" in p for p in problems)


def test_symlinks_in_data_are_refused(tmp_path):
    slot = slot_tree(tmp_path)
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"1")
    (slot / "data").mkdir()
    (slot / "data" / "link.csv").symlink_to(outside)
    status, problems = ts.check_slot(tmp_path, "umls")
    assert status == "incomplete" and any("링크" in p for p in problems)


def test_unknown_entries_at_the_terminology_root_fail_the_check(tmp_path):
    slot_tree(tmp_path)
    (tmp_path / "terminology" / "snomed").mkdir()
    assert ts.main(["--root", str(tmp_path), "check"]) == 1


# --- codex R5 반영 ------------------------------------------------------------------


def test_a_symlinked_slot_json_is_refused_and_never_written_through(tmp_path):
    slot = slot_tree(tmp_path)
    put(slot, "a.csv", b"1")
    outside = tmp_path / "victim.txt"
    outside.write_text("keep me", encoding="utf-8")
    (slot / "slot.json").symlink_to(outside)
    assert ts.check_slot(tmp_path, "umls")[0] == "incomplete"
    ok, message = ts.record(tmp_path, "umls")
    assert not ok and "링크" in message
    assert outside.read_text(encoding="utf-8") == "keep me"


def test_a_symlinked_data_folder_or_slot_is_refused(tmp_path):
    slot = slot_tree(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "a.csv").write_bytes(b"1")
    (slot / "data").symlink_to(elsewhere, target_is_directory=True)
    assert ts.check_slot(tmp_path, "umls")[0] == "incomplete"
    other = slot_tree(tmp_path / "t2", "omop")
    shutil.rmtree(other)
    other.symlink_to(elsewhere, target_is_directory=True)
    assert ts.check_slot(tmp_path / "t2", "omop")[0] == "incomplete"


def test_junctions_count_as_links(tmp_path, monkeypatch):
    slot = slot_tree(tmp_path)
    (slot / "data").mkdir()
    target = slot / "data"
    monkeypatch.setattr(Path, "is_junction", lambda self: self == target, raising=False)
    status, problems = ts.check_slot(tmp_path, "umls")
    assert status == "incomplete" and any("junction" in p for p in problems)


def test_a_symlinked_terminology_root_is_refused_and_never_written_through(tmp_path):
    outside = tmp_path / "outside"
    shutil.copytree(ROOT / "terminology", outside / "terminology")
    (outside / "terminology" / "umls" / "data").mkdir()
    (outside / "terminology" / "umls" / "data" / "a.csv").write_bytes(b"1")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "terminology").symlink_to(outside / "terminology", target_is_directory=True)
    assert ts.check_slot(bundle, "umls")[0] == "incomplete"
    assert ts.record(bundle, "umls")[0] is False
    assert not (outside / "terminology" / "umls" / "slot.json").exists()
