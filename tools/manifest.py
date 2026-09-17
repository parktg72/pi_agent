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
    # graphify 지식그래프 산출물. 소스가 아니라 생성물이라 스테이징 범위 밖이다.
    "graphify-out",
    # install-python-packages.bat이 기본값으로 만드는 가상환경. 대상 PC에서
    # 생기므로 스테이징 시점에는 없고, 만들어지는 순간 수천 개 파일이
    # unexpected:로 쏟아져 무결성 검사가 영구히 빨간불이 된다.
    ".venv",
    # 대상 PC에서 학습해 넣는 LoRA 어댑터(config.env LORA_FILE). 반입물이 아니라
    # 현장 생성물이고 주기적으로 바뀐다. 해시하면 어댑터를 넣은 운영자에게
    # unexpected:가 확정적으로 뜬다 - .venv와 같은 이유다.
    "lora",
    # 오케스트레이션 구성(멀티에이전트 스캐폴드) — 개발 트리 전용이다. 반입
    # 번들에 실리면 verify-bundle이 unexpected:로 쏟아내고, README가 단언하는
    # "지적된 것은 진짜 전송 손상"이 거짓이 된다.
    "_shared",
    "_templates",
    "_local",
    "prep",
    "tasks",
    "assets",
    ".claude",
)
# config.env는 README와 리허설 절차서가 현장에서 채우라고 지시하는 파일이다.
# 해시하면 지시를 따른 운영자에게 hash mismatch가 확정적으로 뜬다.
EXCLUDED_FILES = (
    "STAGING_MANIFEST.json",
    ".gitignore",
    ".gitattributes",
    "config.env",
    # 오케스트레이션 구성의 루트 파일 — 위 EXCLUDED_ROOTS와 같은 이유.
    # 이 목록은 번들 루트에만 적용된다(iter_immutable_files의 at_top 조건).
    # payload 하위에는 README.md·LICENSE·CLAUDE.md 등 동명 파일이 실제로
    # 존재하므로, at_top 없이 이름만으로 제외하면 그것들이 아무 신호 없이
    # 해시 범위 밖으로 나간다. 그 계약은 tests/test_manifest.py가 고정한다.
    "CLAUDE.md",
    "AGENTS.md",
    "README.md",
    "LICENSE",
    "NOTICE",
    "CHANGELOG.md",
    "KNOWN_ISSUES.md",
    "SESSION.template.md",
    # 세션 이어가기 규율이 대상 PC에서 만들고 계속 갱신하는 가변·사적 상태다.
    # config.env와 같은 이유로, 해시하면 규율을 따른 운영자에게 확정 실패가 뜬다.
    "SESSION.md",
    ".mcp.json",
)
# 스테이징 PC에 있지만 반입하지 않는 것. 번들 루트 기준의 정확한 경로로만
# 뺀다(파일 또는 디렉터리) - 이름 비교로 빼면 payload 안의 같은 이름까지 해시
# 범위 밖으로 샌다. 2026-09-17 사용자 결정: 반입 모델은 Q6_K(기본)·Q4_K_M(백업)·
# mmproj뿐이다. 아래 셋은 파일을 옮기지 않고 해시에서만 뺀다. 반입 매체로
# 복사할 때 함께 빼도 된다.
EXCLUDED_PATHS = (
    "models/Qwen3.8-27B-Q8_0.gguf",
    "models/Qwen3.8-27B-Uncensored-GGUF",
    "models/DeepSeek-R1-0528-Qwen3-8B-GGUF",
)
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
            if name not in EXCLUDED_DIR_NAMES
            and not (at_top and name in EXCLUDED_ROOTS)
            and (relative_dir / name).as_posix() not in EXCLUDED_PATHS
        ]
        for name in sorted(filenames):
            if at_top and name in EXCLUDED_FILES:
                continue
            if name.endswith(EXCLUDED_SUFFIXES):
                continue
            relative = (relative_dir / name).as_posix()
            if relative in EXCLUDED_PATHS:
                continue
            yield relative, Path(dirpath) / name


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
        "excludedPaths": list(EXCLUDED_PATHS),
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
