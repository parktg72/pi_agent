"""의료 용어 체계 덤프 슬롯(terminology/<source>/)을 검사하고 파일 목록을 기록한다.

슬롯: kcd8, icd10, atc, umls, omop (tasks/pi-agent-terminology 합의).
- `terminology/<source>/data/`   덤프 원본. gitignore·매니페스트 제외 - 스테이징이든 현장이든 넣을 수 있다.
- `terminology/<source>/slot.json` 출처·라이선스 검토·파일 목록. gitignore·매니페스트 제외.
- `README.md`·`slot.example.json`만 git 추적·매니페스트 해시.

전송 무결성은 slot.json의 files[](bytes·sha256)로 본다. 스테이징 PC에서 `record`로 기록한 뒤
옮기면 대상 PC의 `check`가 전송 검사가 된다.

상태:
- empty      data/에 파일이 없고 slot.json에 기록된 파일도 없다(정상 - 아직 미제공).
- recorded   파일·필수 메타데이터·해시·검토(approved)가 모두 맞다. **적재 가능하다는 뜻이 아니다** -
             파서·적재기가 아직 없고 형식은 검증하지 않았다.
- incomplete 그 밖의 모든 경우. 하나라도 있으면 check가 nonzero로 끝난다.

자동 법률 판정은 하지 않는다. review_status·review_scope·review_basis는 사람이 쓴다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SOURCES = ("kcd8", "icd10", "atc", "umls", "omop")
REQUIRED_FIELDS = (
    "source",
    "distributor",
    "release",
    "acquired_on",
    "source_url",
    "license_terms",
    "review_status",
    "review_scope",
    "review_basis",
)
REVIEW_STATUSES = ("unreviewed", "approved", "rejected")
NOT_LOADABLE = "파서·적재기 없음, 형식 미검증 - recorded는 기록·해시·검토가 맞다는 뜻이지 적재 가능하다는 뜻이 아니다"
_CHUNK = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


SLOT_ENTRIES = ("README.md", "slot.example.json", "slot.json", "data")


def data_files(slot: Path) -> list[str]:
    data = slot / "data"
    if not data.is_dir():
        return []
    return sorted(p.relative_to(data).as_posix() for p in data.rglob("*") if p.is_file() or p.is_symlink())


def _is_link(path: Path) -> bool:
    # Windows junction은 is_symlink()로 잡히지 않는다(Python 3.12 Path.is_junction, codex R5 #1).
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except (OSError, ValueError):
        return False
    return True


def layout_problems(root: Path, slot: Path) -> list[str]:
    """슬롯 구조 자체의 문제: 링크·junction, data가 폴더가 아님, 슬롯 루트에 잘못 둔 파일(codex R4~R6).

    기준은 신뢰된 번들 루트(root)다. terminology\\ 자체가 링크여도 슬롯과 그 부모를 둘 다 바깥으로
    풀면 "안에 있다"로 보이므로, terminology\\부터 root 기준으로 확인한다.
    """
    problems: list[str] = []
    top = root / "terminology"
    if _is_link(top) or (top.exists() and not _inside(top, root)):
        return ["terminology 폴더가 링크·junction이다 - 번들 밖을 가리킬 수 있어 받지 않는다"]
    if _is_link(slot) or (slot.exists() and not _inside(slot, top)):
        return ["슬롯 폴더가 링크·junction이다 - 번들 밖을 가리킬 수 있어 받지 않는다"]
    data = slot / "data"
    for name in ("slot.json", "data"):
        path = slot / name
        if _is_link(path) or (path.exists() and not _inside(path, slot)):
            problems.append(f"{name}이 링크·junction이다 - 슬롯 밖의 파일을 읽거나 덮어쓸 수 있어 받지 않는다")
    if problems:
        return problems
    if data.exists() and not data.is_dir():
        problems.append("data가 폴더가 아니다 - 덤프는 data\\ 폴더 안에 둔다")
    elif data.is_dir():
        for path in data.rglob("*"):
            if _is_link(path) or not _inside(path, data):
                problems.append(f"data/{path.relative_to(data).as_posix()}가 링크·junction이다 - 실제 파일만 둔다")
    if slot.is_dir():
        for entry in sorted(slot.iterdir()):
            if entry.name not in SLOT_ENTRIES:
                problems.append(f"슬롯 루트의 {entry.name}은 모르는 항목이다 - 덤프는 data\\에, 기록은 slot.json에만 둔다")
    return problems


def _valid_relative(name: str) -> bool:
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return False
    parts = name.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def load_slot_json(slot: Path) -> tuple[dict | None, str | None]:
    path = slot / "slot.json"
    if not path.is_file():
        return None, None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"slot.json을 읽지 못했다 - {error}"
    if not isinstance(document, dict):
        return None, "slot.json이 JSON 객체가 아니다"
    return document, None


def check_slot(root: Path, source: str) -> tuple[str, list[str]]:
    slot = root / "terminology" / source
    problems: list[str] = layout_problems(root, slot)
    present = data_files(slot)
    document, error = load_slot_json(slot)
    if error:
        return "incomplete", problems + [error]
    recorded = document.get("files") if document else None
    if recorded is not None and not isinstance(recorded, list):
        return "incomplete", ["files가 목록이 아니다"]
    recorded = recorded or []
    if problems:
        return "incomplete", problems
    if not present and not recorded:
        return "empty", []

    if document is None:
        return "incomplete", ["data/에 파일이 있는데 slot.json이 없다 - slot.example.json을 복사해 채우고 record를 실행하라"]
    for field in REQUIRED_FIELDS:
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"필수 필드 {field}가 비었다")
    if document.get("source") not in (None, "", source):
        problems.append(f"source={document.get('source')!r}가 슬롯 이름 {source}와 다르다")
    status = document.get("review_status")
    if status not in REVIEW_STATUSES:
        problems.append(f"review_status={status!r}는 {' | '.join(REVIEW_STATUSES)} 중 하나여야 한다")
    elif status != "approved":
        problems.append(f"review_status가 {status}다 - 이용 조건 검토가 approved여야 쓴다")

    listed: dict[str, dict] = {}
    for entry in recorded:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            problems.append(f"files 항목 형식이 잘못됐다: {entry!r}")
            continue
        name = entry["path"]
        if not _valid_relative(name):
            problems.append(f"files 경로 {name!r}는 data/ 안의 상대경로가 아니다(절대경로·..·역슬래시 불가)")
            continue
        if name in listed:
            problems.append(f"files에 {name}이 두 번 있다")
            continue
        listed[name] = entry
    for name in present:
        if name not in listed:
            problems.append(f"data/{name}이 files[]에 없다 - record를 다시 실행하고 재검토하라")
    for name, entry in listed.items():
        path = slot / "data" / name
        if not path.is_file():
            problems.append(f"기록된 파일 data/{name}이 없다 - 반입 누락 또는 삭제")
            continue
        size = path.stat().st_size
        if entry.get("bytes") != size:
            problems.append(f"data/{name} 크기 {size}가 기록값 {entry.get('bytes')}과 다르다")
            continue  # 크기가 다르면 해시를 계산하지 않는다(수 GB 파일)
        if entry.get("sha256") != sha256_of(path):
            problems.append(f"data/{name} sha256이 기록값과 다르다 - 전송 손상 또는 다른 파일")
    return ("recorded" if not problems else "incomplete"), problems


def record(root: Path, source: str) -> tuple[bool, str]:
    """data/의 파일을 해시해 files[]를 쓴다. 목록·크기·해시가 바뀌면 검토를 unreviewed로 되돌린다."""
    slot = root / "terminology" / source
    layout = layout_problems(root, slot)
    if layout:
        return False, "; ".join(layout)
    present = data_files(slot)
    if not present:
        return False, f"terminology/{source}/data/에 파일이 없다"
    document, error = load_slot_json(slot)
    if error:
        return False, error
    if document is None:
        example = slot / "slot.example.json"
        document = json.loads(example.read_text(encoding="utf-8")) if example.is_file() else {"source": source}
    files = []
    for name in present:
        path = slot / "data" / name
        files.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256_of(path)})
    changed = document.get("files") != files
    document["files"] = files
    reset = False
    if changed and document.get("review_status") != "unreviewed":
        # 이전 자료에 대한 승인이 새 파일로 넘어가지 않게 한다(codex R3 FIX 2).
        document["review_status"] = "unreviewed"
        reset = True
    target = slot / "slot.json"
    # 쓰기 직전에 다시 확인한다: 검사 뒤 링크로 바뀌었어도 슬롯 밖을 덮어쓰지 않는다.
    if _is_link(target) or (target.exists() and not _inside(target, slot)) or not _inside(slot, root / "terminology"):
        return False, "slot.json이 링크·junction이거나 번들 밖이다 - 쓰지 않았다"
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    note = " - 파일이 바뀌어 review_status를 unreviewed로 되돌렸다. 재검토 후 approved로 쓴다" if reset else ""
    return True, f"terminology/{source}/slot.json에 파일 {len(files)}개를 기록했다{note}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="terminology_slots")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    rec = sub.add_parser("record")
    rec.add_argument("source", choices=SOURCES)
    args = parser.parse_args(argv)

    if args.command == "record":
        ok, message = record(args.root, args.source)
        print(("[ok] " if ok else "[FAIL] ") + message, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    failed = False
    top = args.root / "terminology"
    if top.is_dir():
        for entry in sorted(top.iterdir()):
            if entry.name != "README.md" and entry.name not in SOURCES:
                print(f"[incomplete] terminology/{entry.name} - 모르는 항목이다(슬롯은 {', '.join(SOURCES)})")
                failed = True
    for source in SOURCES:
        status, problems = check_slot(args.root, source)
        print(f"[{status}] terminology/{source}")
        for problem in problems:
            print(f"    - {problem}")
        failed |= status == "incomplete"
    print(f"[info] {NOT_LOADABLE}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
