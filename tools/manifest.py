"""번들의 불변 영역만 해시하는 스테이징 매니페스트.

가변 영역을 넣으면 첫 실행 직후 무결성 검사가 깨진다. 그래서 해시 범위와
git 추적 범위를 같게 둔다.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterator

SCHEMA = "pi_agent.closed_network_stage.v1"
EXCLUDED_ROOTS = ("home", "evidence", "docs", "tests", "win", ".git", ".cache", ".pytest_cache")
EXCLUDED_FILES = ("STAGING_MANIFEST.json", ".gitignore")
_CHUNK = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_immutable_files(root: Path) -> Iterator[tuple[str, Path]]:
    for dirpath, dirnames, filenames in os.walk(root):
        relative_dir = Path(dirpath).relative_to(root)
        top = relative_dir.parts[0] if relative_dir.parts else ""
        if top in EXCLUDED_ROOTS:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in sorted(dirnames) if not (relative_dir.parts == () and d in EXCLUDED_ROOTS)]
        for name in sorted(filenames):
            if relative_dir.parts == () and name in EXCLUDED_FILES:
                continue
            yield (relative_dir / name).as_posix(), Path(dirpath) / name


def build(root: Path, staged_at: str, target: str) -> dict:
    files = []
    total_bytes = 0
    for relative, path in sorted(iter_immutable_files(root), key=lambda pair: pair[0]):
        size = path.stat().st_size
        files.append({"relative": relative, "bytes": size, "sha256": sha256_of(path)})
        total_bytes += size
    return {
        "schema": SCHEMA,
        "stagedAt": staged_at,
        "target": target,
        "excludedRoots": list(EXCLUDED_ROOTS),
        "totals": {"files": len(files), "bytes": total_bytes},
        "files": files,
    }


def verify(root: Path, doc: dict) -> list[str]:
    recorded = {entry["relative"]: entry for entry in doc["files"]}
    present = {relative for relative, _ in iter_immutable_files(root)}
    problems = [f"missing: {rel}" for rel in sorted(set(recorded) - present)]
    problems += [f"unexpected: {rel}" for rel in sorted(present - set(recorded))]
    for rel in sorted(set(recorded) & present):
        entry = recorded[rel]
        path = root / rel
        if path.stat().st_size != entry["bytes"]:
            problems.append(f"size mismatch: {rel}")
        elif sha256_of(path) != entry["sha256"]:
            problems.append(f"hash mismatch: {rel}")
    return problems
