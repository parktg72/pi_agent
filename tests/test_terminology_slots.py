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
    assert "/terminology/*/data/" in ignore and "/terminology/*/slot.json" in ignore
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
