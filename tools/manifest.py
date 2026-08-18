"""번들의 불변 영역만 해시하는 스테이징 매니페스트.

원칙은 하나다 — **불변 영역만 해시한다.** 가변 영역을 넣으면 첫 실행 직후
무결성 검사가 깨지고, 운영자가 검사 결과를 무시하도록 훈련된다. 그러면
전송 손상을 잡는 유일한 장치를 잃는다.

해시 범위는 git 추적 범위와 다르다. `bin/`, `models/`는 gitignore 대상이지만
반입물의 본체이므로 해시하고, `win/`은 git이 추적하지만 번들 루트로 복사된
사본만 해시하므로 제외한다. `config.env`는 운영자가 현장에서 값을 채우라고
지시받는 파일이라 제외한다(원본 템플릿 `config.env.example`은 해시한다).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterator

SCHEMA = "pi_agent.closed_network_stage.v1"
EXCLUDED_ROOTS = (
    "home",
    "evidence",
    "docs",
    "tests",
    "win",
    ".git",
    ".cache",
    ".pytest_cache",
    ".superpowers",
    # install-python-packages.bat이 기본값으로 만드는 가상환경. 대상 PC에서
    # 생기므로 스테이징 시점에는 없고, 만들어지는 순간 수천 개 파일이
    # unexpected:로 쏟아져 무결성 검사가 영구히 빨간불이 된다.
    ".venv",
)
# config.env는 README와 리허설 절차서가 현장에서 채우라고 지시하는 파일이다.
# 해시하면 지시를 따른 운영자에게 hash mismatch가 확정적으로 뜬다.
EXCLUDED_FILES = ("STAGING_MANIFEST.json", ".gitignore", ".gitattributes", "config.env")
# 파이썬 바이트코드는 대상 PC에서 verify_bundle.py가 import되는 순간 다시
# 쓰인다. 즉 검사 대상이 검사 도중 바뀐다. 깊이와 무관하게 제외한다.
EXCLUDED_DIR_NAMES = ("__pycache__",)
EXCLUDED_SUFFIXES = (".pyc", ".pyo")
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
        at_top = relative_dir.parts == ()
        # 하위 디렉터리를 걸러 내려가지 않으므로 여기서 잘라 낸 것은 다시 보이지 않는다.
        # EXCLUDED_ROOTS는 최상위에서만, EXCLUDED_DIR_NAMES는 깊이와 무관하게 자른다.
        dirnames[:] = [
            name
            for name in sorted(dirnames)
            if name not in EXCLUDED_DIR_NAMES and not (at_top and name in EXCLUDED_ROOTS)
        ]
        for name in sorted(filenames):
            if at_top and name in EXCLUDED_FILES:
                continue
            if name.endswith(EXCLUDED_SUFFIXES):
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
        "excludedFiles": list(EXCLUDED_FILES),
        "excludedDirNames": list(EXCLUDED_DIR_NAMES),
        "excludedSuffixes": list(EXCLUDED_SUFFIXES),
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
