# Pi 폐쇄망 윈도우 배포 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 인터넷 없는 윈도우 PC에서 압축 해제만으로 Pi 코딩 에이전트가 로컬 llama.cpp 모델과 툴 왕복까지 수행하는 반입 번들을 만든다.

**Architecture:** WSL 쪽(인터넷 가능)에서 파이썬 스테이징 도구가 상류 자산을 받아 해시를 검증하고 `H:\model\pi_agent` 아래에 번들을 배치한 뒤 불변 영역만 담은 매니페스트를 발행한다. 폐쇄망 쪽은 파이썬 없이 도는 `.bat`/PowerShell 스크립트가 모델을 결정적으로 기동하고, 성공 여부를 증거 파일로 남긴다.

**Tech Stack:** Python 3 표준 라이브러리만(hashlib, zipfile, json, urllib), pytest 9.1.1, Windows batch + PowerShell 5.1, llama.cpp b10470, Pi 0.84.2.

**Spec:** `/mnt/h/model/pi_agent/docs/superpowers/specs/2026-08-18-pi-agent-closed-network-design.md`

## Global Constraints

- llama.cpp 자산은 **CUDA 12.4 빌드만** 쓴다. `cuda-13.3`은 Pascal PTX가 없어 1080 Ti에서 동작하지 않으므로 어떤 경로로도 번들에 들어가면 안 된다.
- llama.cpp 배포 zip은 이미 자기완결이다. CPU zip을 CUDA zip에 병합하지 않는다. 필요한 자산은 **CUDA 12.4 zip + cudart 12.4 zip** 두 개.
- `bin\llama-cuda\`, `bin\llama-vulkan\`, `bin\llama-cpu\`는 **각각 독립 디렉터리**다. 백엔드 DLL을 한 폴더에 섞지 않는다.
- `MSVCP140.dll`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`을 llama 백엔드 디렉터리에 app-local로 둔다. Pi는 이것들이 필요 없다.
- llama-server 인자 고정: `--jinja`, `--host 127.0.0.1`, `-ngl 999`, `--parallel 1`, `-sm layer`. `-sm row` 금지. `-ts`는 실측 free VRAM으로만 설정하고 `1,1,1` 고정 금지(미설정이 기본).
- Pi 실행 시 `PI_OFFLINE=1`, `PI_CODING_AGENT_DIR=%~dp0home\agent`를 배치 파일이 강제한다.
- 매니페스트는 불변 영역만 해시한다. `home/`, `evidence/`, `docs/`, `tools/`, `tests/`, `.git/`는 제외한다.
- 성공 기준은 종료 코드가 아니라 `evidence\`에 남은 증거다.
- 검증된 상류 해시 (2026-08-18 실측):
  - `pi-windows-x64.zip` = `741fc1ae1afecb573ac2888e011188ff446b3940f4aabe1583f60bf55be8a3d0` (45,470,989 bytes)
  - `llama-b10470-bin-win-cuda-12.4-x64.zip` = `e6f3fa9790ab7684ded44ade774dc94742ddb99e4b0abaf1603dab4f3d0803d3` (250,799,028 bytes)

## File Structure

```
/mnt/h/model/pi_agent/
├── tools/                        git 추적. 번들에 함께 실린다 (매니페스트 해시 대상)
│   ├── manifest.py               불변 영역 해시·검증 (폐쇄망에서도 쓰임)
│   ├── wait_model.py             모델 적재 대기 (폐쇄망)
│   ├── verify_bundle.py          매니페스트 대조 (폐쇄망)
│   ├── assets.py                 자산 카탈로그와 다운로드·해시 검증
│   ├── layout.py                 압축 해제·배치·백엔드 분리 가드
│   ├── gguf.py                   GGUF 메타데이터에서 chat_template 확인
│   └── stage.py                  CLI 진입점
├── tests/                        git 추적. pytest, 네트워크 없이 도는 것만
│   ├── test_manifest.py
│   ├── test_assets.py
│   ├── test_layout.py
│   └── test_gguf.py
├── win/                          git 추적. 스테이징 때 번들 루트로 복사됨
│   ├── start-llama.bat
│   ├── start-pi.bat
│   ├── verify-offline.bat
│   ├── config.env.example
│   └── README-폐쇄망.md
├── bin/ models/ home/ evidence/   git 무시. 번들 실체
└── docs/superpowers/{specs,plans}/
```

각 파일은 책임이 하나다. `manifest.py`는 해시만, `layout.py`는 배치와 가드만, `assets.py`는 획득과 검증만 안다. `stage.py`만 이들을 조립한다.

---

### Task 1: 매니페스트 생성과 검증

**Files:**
- Create: `/mnt/h/model/pi_agent/tools/manifest.py`
- Test: `/mnt/h/model/pi_agent/tests/test_manifest.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `manifest.build(root: Path, staged_at: str, target: str) -> dict`, `manifest.verify(root: Path, doc: dict) -> list[str]`, 상수 `manifest.SCHEMA`, `manifest.EXCLUDED_ROOTS`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_manifest.py
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
    (root / "models" / "m.gguf").write_bytes(b"tampered")
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'manifest'`

- [ ] **Step 3: 최소 구현을 쓴다**

```python
# tools/manifest.py
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_manifest.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: 커밋한다**

```bash
cd /mnt/h/model/pi_agent
git add tools/manifest.py tests/test_manifest.py
git commit -m "매니페스트는 불변 영역만 해시한다"
```

---

### Task 2: 자산 카탈로그와 획득

**Files:**
- Create: `/mnt/h/model/pi_agent/tools/assets.py`
- Test: `/mnt/h/model/pi_agent/tests/test_assets.py`

**Interfaces:**
- Consumes: `manifest.sha256_of`
- Produces: `assets.CATALOG: dict[str, Asset]`, `Asset(name, url, sha256, bytes)` 데이터클래스, `assets.verify_downloaded(path: Path, asset: Asset) -> list[str]`, `assets.forbidden_reason(name_or_url: str) -> str | None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_assets.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import assets


def test_catalog_pins_the_two_verified_hashes():
    pi = assets.CATALOG["pi"]
    assert pi.name == "pi-windows-x64.zip"
    assert pi.sha256 == "741fc1ae1afecb573ac2888e011188ff446b3940f4aabe1583f60bf55be8a3d0"
    assert pi.bytes == 45470989
    cuda = assets.CATALOG["llama-cuda"]
    assert cuda.name == "llama-b10470-bin-win-cuda-12.4-x64.zip"
    assert cuda.sha256 == "e6f3fa9790ab7684ded44ade774dc94742ddb99e4b0abaf1603dab4f3d0803d3"


def test_catalog_carries_cudart_vulkan_and_cpu():
    for key in ("llama-cudart", "llama-vulkan", "llama-cpu"):
        assert key in assets.CATALOG
        assert assets.CATALOG[key].url.startswith("https://github.com/ggml-org/llama.cpp/releases/download/b10470/")


def test_no_catalog_entry_may_reference_cuda_13():
    for key, asset in assets.CATALOG.items():
        assert assets.forbidden_reason(asset.name) is None, key
        assert assets.forbidden_reason(asset.url) is None, key


def test_cuda_13_is_refused_by_name_and_by_url():
    assert assets.forbidden_reason("llama-b10470-bin-win-cuda-13.3-x64.zip") is not None
    assert assets.forbidden_reason("https://example/cudart-llama-bin-win-cuda-13.4-arm64.zip") is not None


def test_verify_downloaded_detects_size_and_hash_drift(tmp_path):
    asset = assets.Asset(name="x.zip", url="https://example/x.zip", sha256="0" * 64, bytes=4)
    path = tmp_path / "x.zip"
    path.write_bytes(b"abcd")
    problems = assets.verify_downloaded(path, asset)
    assert any("sha256" in p for p in problems)

    short = assets.Asset(name="x.zip", url="https://example/x.zip", sha256="0" * 64, bytes=99)
    problems = assets.verify_downloaded(path, short)
    assert any("bytes" in p for p in problems)


def test_verify_downloaded_is_quiet_when_the_file_matches(tmp_path):
    import hashlib

    payload = b"abcd"
    path = tmp_path / "x.zip"
    path.write_bytes(payload)
    asset = assets.Asset(
        name="x.zip",
        url="https://example/x.zip",
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
    )
    assert assets.verify_downloaded(path, asset) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_assets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assets'`

- [ ] **Step 3: 최소 구현을 쓴다**

`llama-cudart`, `llama-vulkan`, `llama-cpu`의 `sha256`/`bytes`는 아직 실측하지 않았으므로 `None`으로 둔다. Step 5에서 실제로 받아 채운다. `None`인 채로 스테이징하면 Task 5의 CLI가 거부한다.

```python
# tools/assets.py
"""반입 대상 상류 자산의 카탈로그와 획득.

CUDA 13 계열은 Pascal PTX가 없어 1080 Ti에서 동작하지 않는다. 이름이나 URL
어디에 나타나든 거부한다 — 파일명만 보면 최신이라 고르기 쉬운 함정이다.
"""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

from manifest import sha256_of

_LLAMA_TAG = "b10470"
_LLAMA_BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{_LLAMA_TAG}/"
_PI_BASE = "https://github.com/earendil-works/pi/releases/download/v0.84.2/"
_FORBIDDEN_TOKENS = ("cuda-13", "cuda_13", "cuda-14", "cuda_14")


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    sha256: str | None
    bytes: int | None


def _llama(name: str, sha256: str | None = None, size: int | None = None) -> Asset:
    return Asset(name=name, url=_LLAMA_BASE + name, sha256=sha256, bytes=size)


CATALOG: dict[str, Asset] = {
    "pi": Asset(
        name="pi-windows-x64.zip",
        url=_PI_BASE + "pi-windows-x64.zip",
        sha256="741fc1ae1afecb573ac2888e011188ff446b3940f4aabe1583f60bf55be8a3d0",
        bytes=45470989,
    ),
    "llama-cuda": _llama(
        f"llama-{_LLAMA_TAG}-bin-win-cuda-12.4-x64.zip",
        "e6f3fa9790ab7684ded44ade774dc94742ddb99e4b0abaf1603dab4f3d0803d3",
        250799028,
    ),
    "llama-cudart": _llama("cudart-llama-bin-win-cuda-12.4-x64.zip"),
    "llama-vulkan": _llama(f"llama-{_LLAMA_TAG}-bin-win-vulkan-x64.zip"),
    "llama-cpu": _llama(f"llama-{_LLAMA_TAG}-bin-win-cpu-x64.zip"),
}


def forbidden_reason(name_or_url: str) -> str | None:
    lowered = name_or_url.lower()
    for token in _FORBIDDEN_TOKENS:
        if token in lowered:
            return f"{token} 계열은 Pascal(compute 6.1)용 PTX를 담지 않는다"
    return None


def verify_downloaded(path: Path, asset: Asset) -> list[str]:
    problems: list[str] = []
    if not path.is_file():
        return [f"missing file: {path}"]
    if asset.bytes is not None and path.stat().st_size != asset.bytes:
        problems.append(f"bytes mismatch: {path.name} has {path.stat().st_size}, expected {asset.bytes}")
    if asset.sha256 is not None:
        actual = sha256_of(path)
        if actual != asset.sha256:
            problems.append(f"sha256 mismatch: {path.name} is {actual}, expected {asset.sha256}")
    return problems


def download(asset: Asset, into: Path) -> Path:
    reason = forbidden_reason(asset.url)
    if reason:
        raise ValueError(f"거부된 자산 {asset.name}: {reason}")
    into.mkdir(parents=True, exist_ok=True)
    destination = into / asset.name
    if destination.exists() and not verify_downloaded(destination, asset):
        return destination
    with urllib.request.urlopen(asset.url) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    return destination
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_assets.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 남은 세 자산을 실제로 받아 해시를 못 박는다**

```bash
cd /mnt/h/model/pi_agent
mkdir -p .cache
for name in cudart-llama-bin-win-cuda-12.4-x64.zip llama-b10470-bin-win-vulkan-x64.zip llama-b10470-bin-win-cpu-x64.zip; do
  curl -fL --retry 3 -o ".cache/$name" "https://github.com/ggml-org/llama.cpp/releases/download/b10470/$name"
done
sha256sum .cache/*.zip
stat -c '%n %s' .cache/*.zip
```

출력된 값을 `assets.py`의 `llama-cudart`, `llama-vulkan`, `llama-cpu` 항목에 채워 넣고, `test_catalog_carries_cudart_vulkan_and_cpu`에 다음 단언을 추가한다:

```python
    for key in ("llama-cudart", "llama-vulkan", "llama-cpu"):
        assert assets.CATALOG[key].sha256 is not None and len(assets.CATALOG[key].sha256) == 64
        assert assets.CATALOG[key].bytes and assets.CATALOG[key].bytes > 0
```

- [ ] **Step 6: 테스트를 다시 돌린다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_assets.py -v`
Expected: PASS — 6 passed

- [ ] **Step 7: 커밋한다**

```bash
cd /mnt/h/model/pi_agent
git add tools/assets.py tests/test_assets.py
git commit -m "자산 카탈로그를 실측 해시로 고정하고 CUDA 13 계열을 거부한다"
```

---

### Task 3: 번들 배치와 백엔드 분리 가드

**Files:**
- Create: `/mnt/h/model/pi_agent/tools/layout.py`
- Test: `/mnt/h/model/pi_agent/tests/test_layout.py`

**Interfaces:**
- Consumes: 없음
- Produces: `layout.extract(zip_path: Path, destination: Path) -> None`, `layout.check_backend_dir(destination: Path, backend: str) -> list[str]`, `layout.place_vc_runtime(source: Path, destination: Path) -> list[str]`, 상수 `layout.VC_RUNTIME_DLLS`, `layout.BACKEND_MARKERS`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_layout.py
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import layout


def make_zip(tmp_path: Path, names: list[str]) -> Path:
    archive = tmp_path / "asset.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name in names:
            zf.writestr(name, b"stub")
    return archive


def test_extract_places_every_member(tmp_path):
    archive = make_zip(tmp_path, ["llama-server.exe", "ggml-cuda.dll", "ggml-base.dll"])
    destination = tmp_path / "bin" / "llama-cuda"
    layout.extract(archive, destination)
    assert (destination / "llama-server.exe").is_file()
    assert (destination / "ggml-cuda.dll").is_file()


def test_extract_refuses_paths_that_escape_the_destination(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escaped.txt", b"nope")
    destination = tmp_path / "bin" / "llama-cuda"
    try:
        layout.extract(archive, destination)
    except ValueError as error:
        assert "escaped" in str(error)
    else:
        raise AssertionError("탈출 경로를 허용했다")
    assert not (tmp_path / "bin" / "escaped.txt").exists()


def test_backend_dir_needs_server_and_its_own_backend_dll(tmp_path):
    destination = tmp_path / "bin" / "llama-cuda"
    destination.mkdir(parents=True)
    assert layout.check_backend_dir(destination, "cuda") != []

    (destination / "llama-server.exe").write_bytes(b"x")
    (destination / "ggml-cuda.dll").write_bytes(b"x")
    assert layout.check_backend_dir(destination, "cuda") == []


def test_backend_dirs_may_not_be_mixed(tmp_path):
    destination = tmp_path / "bin" / "llama-cuda"
    destination.mkdir(parents=True)
    (destination / "llama-server.exe").write_bytes(b"x")
    (destination / "ggml-cuda.dll").write_bytes(b"x")
    (destination / "ggml-vulkan.dll").write_bytes(b"x")
    problems = layout.check_backend_dir(destination, "cuda")
    assert any("ggml-vulkan.dll" in p for p in problems)


def test_place_vc_runtime_copies_all_three_dlls(tmp_path):
    source = tmp_path / "vc"
    source.mkdir()
    for name in layout.VC_RUNTIME_DLLS:
        (source / name).write_bytes(b"dll")
    destination = tmp_path / "bin" / "llama-cuda"
    destination.mkdir(parents=True)
    assert layout.place_vc_runtime(source, destination) == []
    for name in layout.VC_RUNTIME_DLLS:
        assert (destination / name).is_file()


def test_place_vc_runtime_reports_what_is_missing(tmp_path):
    source = tmp_path / "vc"
    source.mkdir()
    (source / "VCRUNTIME140.dll").write_bytes(b"dll")
    destination = tmp_path / "bin" / "llama-cuda"
    destination.mkdir(parents=True)
    problems = layout.place_vc_runtime(source, destination)
    assert any("MSVCP140.dll" in p for p in problems)
    assert any("VCRUNTIME140_1.dll" in p for p in problems)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_layout.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'layout'`

- [ ] **Step 3: 최소 구현을 쓴다**

```python
# tools/layout.py
"""자산을 번들 디렉터리로 푸는 일과, 푼 결과가 옳은지 보는 가드.

백엔드 디렉터리를 섞으면 어느 백엔드가 로드됐는지 확정할 수 없다. 그래서
자기 백엔드 DLL만 있어야 한다고 못 박는다.
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

VC_RUNTIME_DLLS = ("MSVCP140.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll")
BACKEND_MARKERS = {"cuda": "ggml-cuda.dll", "vulkan": "ggml-vulkan.dll", "cpu": "ggml-cpu-x64.dll"}


def extract(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    resolved_destination = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            target = (resolved_destination / member).resolve()
            if not str(target).startswith(str(resolved_destination)):
                raise ValueError(f"{zip_path.name}의 항목이 대상 밖으로 escaped: {member}")
        archive.extractall(resolved_destination)


def check_backend_dir(destination: Path, backend: str) -> list[str]:
    problems: list[str] = []
    if not (destination / "llama-server.exe").is_file():
        problems.append(f"{destination}: llama-server.exe 없음")
    own_marker = BACKEND_MARKERS[backend]
    if not (destination / own_marker).is_file():
        problems.append(f"{destination}: {own_marker} 없음")
    for other_backend, marker in BACKEND_MARKERS.items():
        if other_backend == backend or marker == own_marker:
            continue
        if other_backend == "cpu":
            continue  # 배포 zip이 CPU 백엔드를 모든 빌드에 함께 넣는다
        if (destination / marker).is_file():
            problems.append(f"{destination}: 다른 백엔드 {marker}가 섞였다")
    return problems


def place_vc_runtime(source: Path, destination: Path) -> list[str]:
    problems: list[str] = []
    for name in VC_RUNTIME_DLLS:
        origin = source / name
        if not origin.is_file():
            problems.append(f"VC++ 런타임 {name}을 {source}에서 찾지 못했다")
            continue
        shutil.copy2(origin, destination / name)
    return problems
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_layout.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 커밋한다**

```bash
cd /mnt/h/model/pi_agent
git add tools/layout.py tests/test_layout.py
git commit -m "백엔드 디렉터리를 분리하고 섞임을 거부한다"
```

---

### Task 4: GGUF 채팅 템플릿 검사기

모델 파일이 툴 호출에 쓸 `tokenizer.chat_template`을 실제로 담고 있는지 반입 전에 본다. 없으면 `--jinja`를 줘도 툴 호출이 성립하지 않는다.

**Files:**
- Create: `/mnt/h/model/pi_agent/tools/gguf.py`
- Test: `/mnt/h/model/pi_agent/tests/test_gguf.py`

**Interfaces:**
- Consumes: 없음
- Produces: `gguf.read_metadata(path: Path, keys: tuple[str, ...]) -> dict[str, str]`, `gguf.check_tool_capable(path: Path) -> list[str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_gguf.py
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import gguf

GGUF_TYPE_UINT32 = 4
GGUF_TYPE_STRING = 8


def _string(value: bytes) -> bytes:
    return struct.pack("<Q", len(value)) + value


def write_gguf(path: Path, pairs: list[tuple[str, int, bytes]]) -> Path:
    body = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", len(pairs))
    for key, value_type, encoded in pairs:
        body += _string(key.encode()) + struct.pack("<I", value_type) + encoded
    path.write_bytes(body)
    return path


def test_read_metadata_returns_requested_string_keys(tmp_path):
    path = write_gguf(
        tmp_path / "m.gguf",
        [
            ("general.architecture", GGUF_TYPE_STRING, _string(b"qwen3moe")),
            ("tokenizer.chat_template", GGUF_TYPE_STRING, _string(b"{% for m in messages %}")),
        ],
    )
    found = gguf.read_metadata(path, ("general.architecture", "tokenizer.chat_template"))
    assert found["general.architecture"] == "qwen3moe"
    assert found["tokenizer.chat_template"].startswith("{% for m in messages %}")


def test_read_metadata_skips_values_it_does_not_need(tmp_path):
    path = write_gguf(
        tmp_path / "m.gguf",
        [
            ("some.count", GGUF_TYPE_UINT32, struct.pack("<I", 7)),
            ("tokenizer.chat_template", GGUF_TYPE_STRING, _string(b"template")),
        ],
    )
    found = gguf.read_metadata(path, ("tokenizer.chat_template",))
    assert found == {"tokenizer.chat_template": "template"}


def test_check_tool_capable_complains_when_the_template_is_absent(tmp_path):
    path = write_gguf(tmp_path / "m.gguf", [("general.architecture", GGUF_TYPE_STRING, _string(b"llama"))])
    problems = gguf.check_tool_capable(path)
    assert any("tokenizer.chat_template" in p for p in problems)


def test_check_tool_capable_is_quiet_on_a_template_that_mentions_tools(tmp_path):
    template = b"{% if tools %}{{ tool_call }}{% endif %}"
    path = write_gguf(tmp_path / "m.gguf", [("tokenizer.chat_template", GGUF_TYPE_STRING, _string(template))])
    assert gguf.check_tool_capable(path) == []


def test_check_tool_capable_flags_a_template_without_any_tool_hook(tmp_path):
    template = b"{% for message in messages %}{{ message.content }}{% endfor %}"
    path = write_gguf(tmp_path / "m.gguf", [("tokenizer.chat_template", GGUF_TYPE_STRING, _string(template))])
    problems = gguf.check_tool_capable(path)
    assert any("tool" in p for p in problems)


def test_rejects_a_file_that_is_not_gguf(tmp_path):
    path = tmp_path / "not.gguf"
    path.write_bytes(b"XXXX" + b"\x00" * 32)
    try:
        gguf.read_metadata(path, ("tokenizer.chat_template",))
    except ValueError as error:
        assert "GGUF" in str(error)
    else:
        raise AssertionError("GGUF가 아닌 파일을 받아들였다")
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_gguf.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gguf'`

- [ ] **Step 3: 최소 구현을 쓴다**

```python
# tools/gguf.py
"""GGUF 헤더에서 메타데이터 문자열만 읽는다.

가중치는 건드리지 않는다. 목적은 하나 — 반입 전에 tokenizer.chat_template의
존재와 툴 훅 여부를 보는 것이다. 이게 없으면 --jinja를 줘도 툴 호출이
성립하지 않는다.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO

_SCALAR_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_TYPE_STRING = 8
_TYPE_ARRAY = 9


def _read(handle: BinaryIO, fmt: str):
    size = struct.calcsize(fmt)
    return struct.unpack(fmt, handle.read(size))[0]


def _read_string(handle: BinaryIO) -> str:
    length = _read(handle, "<Q")
    return handle.read(length).decode("utf-8", errors="replace")


def _skip_value(handle: BinaryIO, value_type: int) -> None:
    if value_type == _TYPE_STRING:
        handle.seek(_read(handle, "<Q"), 1)
    elif value_type == _TYPE_ARRAY:
        element_type = _read(handle, "<I")
        count = _read(handle, "<Q")
        for _ in range(count):
            _skip_value(handle, element_type)
    else:
        handle.seek(_SCALAR_SIZES[value_type], 1)


def read_metadata(path: Path, keys: tuple[str, ...]) -> dict[str, str]:
    wanted = set(keys)
    found: dict[str, str] = {}
    with path.open("rb") as handle:
        if handle.read(4) != b"GGUF":
            raise ValueError(f"{path.name}은 GGUF 파일이 아니다")
        _read(handle, "<I")  # version
        _read(handle, "<Q")  # tensor count
        kv_count = _read(handle, "<Q")
        for _ in range(kv_count):
            key = _read_string(handle)
            value_type = _read(handle, "<I")
            if key in wanted and value_type == _TYPE_STRING:
                found[key] = _read_string(handle)
            else:
                _skip_value(handle, value_type)
            if len(found) == len(wanted):
                break
    return found


def check_tool_capable(path: Path) -> list[str]:
    metadata = read_metadata(path, ("tokenizer.chat_template",))
    template = metadata.get("tokenizer.chat_template")
    if not template:
        return [f"{path.name}: tokenizer.chat_template이 없다 — 툴 호출이 성립하지 않는다"]
    lowered = template.lower()
    if "tool" not in lowered:
        return [f"{path.name}: chat_template에 tool 훅이 보이지 않는다 — 리허설에서 왕복을 반드시 확인하라"]
    return []
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_gguf.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 커밋한다**

```bash
cd /mnt/h/model/pi_agent
git add tools/gguf.py tests/test_gguf.py
git commit -m "GGUF의 chat_template을 반입 전에 확인한다"
```

---

### Task 5: 스테이징 CLI

**Files:**
- Create: `/mnt/h/model/pi_agent/tools/stage.py`
- Test: `/mnt/h/model/pi_agent/tests/test_stage.py`

**Interfaces:**
- Consumes: `assets.CATALOG`, `assets.download`, `assets.verify_downloaded`, `layout.extract`, `layout.check_backend_dir`, `layout.place_vc_runtime`, `manifest.build`, `manifest.verify`, `gguf.check_tool_capable`
- Produces: `stage.plan_targets() -> dict[str, tuple[str, str]]` (자산 키 → (번들 상대 경로, 백엔드 이름 또는 빈 문자열)), `stage.main(argv: list[str]) -> int`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# tests/test_stage.py
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_stage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'stage'`

- [ ] **Step 3: 최소 구현을 쓴다**

```python
# tools/stage.py
"""스테이징 CLI — fetch, layout, manifest, verify, model-check.

해시가 고정되지 않은 자산은 받지 않는다. 핀 없는 다운로드는 다음 릴리스가
조용히 다른 것을 주어도 알 수 없다.
"""
from __future__ import annotations

import argparse
import datetime as _datetime
import json
import sys
from pathlib import Path

import assets
import gguf
import layout
import manifest

_TARGETS: dict[str, tuple[str, str]] = {
    "pi": ("bin/pi", ""),
    "llama-cuda": ("bin/llama-cuda", "cuda"),
    "llama-cudart": ("bin/llama-cuda", ""),
    "llama-vulkan": ("bin/llama-vulkan", "vulkan"),
    "llama-cpu": ("bin/llama-cpu", "cpu"),
}


def plan_targets() -> dict[str, tuple[str, str]]:
    return dict(_TARGETS)


def _fetch(root: Path, cache: Path) -> int:
    unpinned = [key for key, asset in assets.CATALOG.items() if not asset.sha256 or not asset.bytes]
    if unpinned:
        print(f"[FAIL] 해시가 고정되지 않은 자산: {', '.join(sorted(unpinned))}", file=sys.stderr)
        return 1
    for key, asset in sorted(assets.CATALOG.items()):
        path = assets.download(asset, cache)
        problems = assets.verify_downloaded(path, asset)
        if problems:
            for problem in problems:
                print(f"[FAIL] {problem}", file=sys.stderr)
            return 1
        print(f"[ok] {key} {asset.name}")
    return 0


def _layout(root: Path, cache: Path, vc_source: Path | None) -> int:
    problems: list[str] = []
    for key, asset in sorted(assets.CATALOG.items()):
        relative, backend = _TARGETS[key]
        destination = root / relative
        layout.extract(cache / asset.name, destination)
        print(f"[ok] {asset.name} -> {relative}")
    for key, (relative, backend) in sorted(_TARGETS.items()):
        if backend:
            problems += layout.check_backend_dir(root / relative, backend)
    if vc_source is not None:
        for relative in sorted({rel for rel, backend in _TARGETS.values() if backend}):
            problems += layout.place_vc_runtime(vc_source, root / relative)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    return 1 if problems else 0


def _manifest(root: Path, target: str) -> int:
    stamped = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = manifest.build(root, staged_at=stamped, target=target)
    (root / "STAGING_MANIFEST.json").write_text(json.dumps(document, indent=2, ensure_ascii=False))
    print(f"[ok] {document['totals']['files']} files, {document['totals']['bytes']} bytes")
    return 0


def _verify(root: Path) -> int:
    document = json.loads((root / "STAGING_MANIFEST.json").read_text())
    problems = manifest.verify(root, document)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if not problems:
        print("[ok] 매니페스트와 일치한다")
    return 1 if problems else 0


def _model_check(root: Path) -> int:
    models = sorted((root / "models").glob("*.gguf"))
    if not models:
        print("[FAIL] models/ 에 GGUF가 없다", file=sys.stderr)
        return 1
    problems: list[str] = []
    for model in models:
        found = gguf.check_tool_capable(model)
        problems += found
        print(f"[{'FAIL' if found else 'ok'}] {model.name}")
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="stage")
    parser.add_argument("command", choices=["fetch", "layout", "manifest", "verify", "model-check"])
    parser.add_argument("--root", default="/mnt/h/model/pi_agent")
    parser.add_argument("--cache", default="/mnt/h/model/pi_agent/.cache")
    parser.add_argument("--target", default="H:\\model\\pi_agent")
    parser.add_argument("--vc-source", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root)
    cache = Path(args.cache)
    if args.command == "fetch":
        return _fetch(root, cache)
    if args.command == "layout":
        return _layout(root, cache, Path(args.vc_source) if args.vc_source else None)
    if args.command == "manifest":
        return _manifest(root, args.target)
    if args.command == "verify":
        return _verify(root)
    return _model_check(root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/ -v`
Expected: PASS — 전체 스위트 통과 (manifest 5 + assets 6 + layout 6 + gguf 6 + stage 4)

- [ ] **Step 5: 커밋한다**

```bash
cd /mnt/h/model/pi_agent
git add tools/stage.py tests/test_stage.py
git commit -m "스테이징 CLI를 붙이고 핀 없는 자산을 거부한다"
```

---

### Task 6: 폐쇄망 실행 계층

폐쇄망 PC에 Python 3.12가 설치되어 있다. 따라서 검증 로직을 PowerShell에 두 번째로 구현하지 않는다 — Task 1의 `manifest.verify`를 그대로 쓴다. 배치 파일은 얇은 진입점 역할만 하고, 판단이 들어가는 부분은 테스트가 있는 파이썬이 맡는다.

`.bat`이 파이썬을 부르는 방법은 `PYTHON_CMD`로 재정의할 수 있고, 기본값은 `py -3.12`이며 실패하면 `python`으로 넘어간다. 둘 다 없으면 명확히 실패한다.

**Files:**
- Create: `/mnt/h/model/pi_agent/tools/wait_model.py`
- Create: `/mnt/h/model/pi_agent/tools/verify_bundle.py`
- Create: `/mnt/h/model/pi_agent/win/config.env.example`
- Create: `/mnt/h/model/pi_agent/win/start-llama.bat`
- Create: `/mnt/h/model/pi_agent/win/start-pi.bat`
- Create: `/mnt/h/model/pi_agent/win/verify-offline.bat`
- Create: `/mnt/h/model/pi_agent/win/README-폐쇄망.md`
- Test: `/mnt/h/model/pi_agent/tests/test_wait_model.py`
- Test: `/mnt/h/model/pi_agent/tests/test_win_scripts.py`

**Interfaces:**
- Consumes: Task 5의 번들 레이아웃(`bin\llama-cuda\llama-server.exe`, `bin\pi\pi.exe`), Task 1의 `manifest.verify`와 `STAGING_MANIFEST.json` 스키마
- Produces: `wait_model.wait_for_alias(fetch, alias, timeout_s, sleep) -> bool`, `wait_model.main(argv) -> int`, `verify_bundle.main(argv) -> int`, 번들 루트에 놓일 `.bat` 3종. `config.env`가 정의하는 변수: `LLAMA_BACKEND`, `LLAMA_PORT`, `LLAMA_CTX`, `MODEL_FILE`, `MODEL_ALIAS`, `GPU_TENSOR_SPLIT`, `PI_PROVIDER`, `PYTHON_CMD`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

스크립트가 스펙의 고정 규칙을 실제로 담고 있는지 텍스트로 검사한다. 윈도우가 없으므로 실행이 아니라 내용이 검사 대상이다.

```python
# tests/test_win_scripts.py
from pathlib import Path

WIN = Path(__file__).resolve().parents[1] / "win"


def read(name: str) -> str:
    return (WIN / name).read_text(encoding="utf-8")


def test_start_llama_pins_the_required_server_arguments():
    body = read("start-llama.bat")
    for required in ("--jinja", "--host 127.0.0.1", "-ngl 999", "--parallel 1", "-sm layer"):
        assert required in body, required


def test_start_llama_never_hardcodes_a_tensor_split():
    body = read("start-llama.bat")
    assert "-ts 1,1,1" not in body
    assert "GPU_TENSOR_SPLIT" in body


def test_start_llama_refuses_to_run_without_model_file_and_alias():
    body = read("start-llama.bat")
    assert "if not defined MODEL_FILE" in body
    assert "if not defined MODEL_ALIAS" in body


def test_start_pi_seals_offline_mode_and_the_portable_home():
    body = read("start-pi.bat")
    assert 'set "PI_OFFLINE=1"' in body
    assert 'set "PI_CODING_AGENT_DIR=%~dp0home\\agent"' in body
    assert "LLAMA_BASE_URL" in body


def test_start_pi_waits_for_the_model_before_launching():
    body = read("start-pi.bat")
    assert "wait_model.py" in body
    assert "errorlevel 1" in body
    index_wait = body.index("wait_model.py")
    index_pi = body.index("bin\\pi\\pi.exe")
    assert index_wait < index_pi, "모델 준비 확인이 Pi 기동보다 먼저여야 한다"


def test_batch_files_resolve_python_before_using_it():
    for name in ("start-pi.bat", "verify-offline.bat"):
        body = read(name)
        assert "PYTHON_CMD" in body, name
        assert "py -3.12" in body, name


def test_verify_offline_collects_every_required_piece_of_evidence():
    body = read("verify-offline.bat")
    for required in ("nvidia-smi", "verify_bundle.py", "v1/models", "pktmon", "evidence"):
        assert required in body, required


def test_manifest_verification_is_not_reimplemented_in_powershell():
    for path in WIN.rglob("*.ps1"):
        assert "Get-FileHash" not in path.read_text(encoding="utf-8"), path.name


def test_no_script_mentions_cuda_13():
    for name in ("start-llama.bat", "start-pi.bat", "verify-offline.bat", "config.env.example"):
        assert "cuda-13" not in read(name).lower()


def test_config_example_documents_every_variable_the_scripts_read():
    example = read("config.env.example")
    for variable in ("LLAMA_BACKEND", "LLAMA_PORT", "LLAMA_CTX", "MODEL_FILE", "MODEL_ALIAS", "GPU_TENSOR_SPLIT"):
        assert variable in example, variable
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_win_scripts.py -v`
Expected: FAIL — `FileNotFoundError: .../win/start-llama.bat`

- [ ] **Step 3: `config.env.example`을 쓴다**

```bat
@echo off
rem 폐쇄망 PC에서 config.env 로 복사한 뒤 값을 채운다.

rem 사용할 백엔드 디렉터리 접미사: cuda | vulkan | cpu
set "LLAMA_BACKEND=cuda"

rem llama-server 포트. 127.0.0.1에만 바인딩된다.
set "LLAMA_PORT=8080"

rem 컨텍스트 길이. 32768은 KV 캐시 약 3.0 GiB를 쓴다.
set "LLAMA_CTX=32768"

rem models\ 안의 정확한 GGUF 파일명.
set "MODEL_FILE="

rem Pi가 지정할 모델 ID. /v1/models 에 이 이름으로 나타난다.
set "MODEL_ALIAS="

rem 3장 분산 비율. nvidia-smi로 실측한 free VRAM에 맞춰 정한다.
rem 비워두면 llama.cpp 기본 분배를 쓴다. 1,1,1 고정은 금지한다.
set "GPU_TENSOR_SPLIT="

rem Pi가 llama.cpp 제공자를 부르는 이름. 리허설에서 pi --list-models로 확인해 채운다.
set "PI_PROVIDER="

rem 파이썬 실행 방법. 비워두면 py -3.12 를 먼저, 실패하면 python 을 쓴다.
rem 둘 다 PATH에 없으면 전체 경로를 여기에 적는다.
set "PYTHON_CMD="
```

- [ ] **Step 4: `start-llama.bat`을 쓴다**

```bat
@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%config.env" call "%ROOT%config.env"

if not defined LLAMA_BACKEND set "LLAMA_BACKEND=cuda"
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
if not defined LLAMA_CTX set "LLAMA_CTX=32768"

set "LLAMA_DIR=%ROOT%bin\llama-%LLAMA_BACKEND%"
if not exist "%LLAMA_DIR%\llama-server.exe" (
  echo [FAIL] %LLAMA_DIR%\llama-server.exe 없음
  exit /b 2
)
if not defined MODEL_FILE (
  echo [FAIL] MODEL_FILE 미설정 - config.env를 채워라
  exit /b 2
)
if not defined MODEL_ALIAS (
  echo [FAIL] MODEL_ALIAS 미설정 - config.env를 채워라
  exit /b 2
)
if not exist "%ROOT%models\%MODEL_FILE%" (
  echo [FAIL] %ROOT%models\%MODEL_FILE% 없음
  exit /b 2
)

set "TS_ARG="
if defined GPU_TENSOR_SPLIT set "TS_ARG=-ts %GPU_TENSOR_SPLIT%"

echo [info] %LLAMA_BACKEND% 백엔드로 %MODEL_FILE% 를 %MODEL_ALIAS% 로 올린다
"%LLAMA_DIR%\llama-server.exe" ^
  -m "%ROOT%models\%MODEL_FILE%" ^
  --alias "%MODEL_ALIAS%" ^
  --jinja ^
  --host 127.0.0.1 ^
  --port %LLAMA_PORT% ^
  -ngl 999 ^
  -c %LLAMA_CTX% ^
  --parallel 1 ^
  -sm layer %TS_ARG%
exit /b %errorlevel%
```

- [ ] **Step 5a: 모델 준비 대기의 실패하는 테스트를 쓴다**

시간과 네트워크를 주입 가능하게 만들어 테스트가 실제로 기다리지 않게 한다.

```python
# tests/test_wait_model.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import wait_model


def test_returns_true_as_soon_as_the_alias_appears():
    responses = [
        ConnectionError("서버 없음"),
        {"data": [{"id": "other-model"}]},
        {"data": [{"id": "other-model"}, {"id": "target"}]},
    ]

    def fetch():
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    slept = []
    assert wait_model.wait_for_alias(fetch, "target", timeout_s=100, sleep=slept.append) is True
    assert len(slept) == 2, "필요한 만큼만 기다려야 한다"


def test_returns_false_when_the_alias_never_appears():
    def fetch():
        return {"data": [{"id": "other-model"}]}

    elapsed = []

    def sleep(seconds):
        elapsed.append(seconds)
        if len(elapsed) > 50:
            raise AssertionError("타임아웃이 걸리지 않았다")

    assert wait_model.wait_for_alias(fetch, "target", timeout_s=10, sleep=sleep) is False


def test_a_server_that_never_answers_times_out_rather_than_hanging():
    def fetch():
        raise ConnectionError("서버 없음")

    assert wait_model.wait_for_alias(fetch, "target", timeout_s=10, sleep=lambda _: None) is False


def test_a_malformed_payload_is_treated_as_not_ready():
    def fetch():
        return {"unexpected": "shape"}

    assert wait_model.wait_for_alias(fetch, "target", timeout_s=5, sleep=lambda _: None) is False
```

- [ ] **Step 5b: 테스트가 실패하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_wait_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wait_model'`

- [ ] **Step 5c: `tools/wait_model.py`를 쓴다**

```python
# tools/wait_model.py
"""모델이 적재될 때까지 기다린다. 준비되기 전에 Pi를 띄우지 않기 위한 관문.

폐쇄망에서 무인 기동하므로 무한 대기는 금지다. 시간과 네트워크를 인자로
받아 테스트가 실제로 기다리지 않게 한다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from typing import Callable

_POLL_SECONDS = 5


def wait_for_alias(
    fetch: Callable[[], dict],
    alias: str,
    timeout_s: float,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> bool:
    deadline = now() + timeout_s
    while True:
        try:
            payload = fetch()
            ids = [entry.get("id") for entry in payload.get("data", [])]
            if alias in ids:
                print(f"[ok] {alias} 준비됨")
                return True
            print(f"[wait] 적재된 모델: {', '.join(i for i in ids if i) or '없음'}")
        except Exception as error:  # 서버가 아직 안 떴거나 응답이 깨졌다
            print(f"[wait] {type(error).__name__}: {error}")
        if now() + _POLL_SECONDS > deadline:
            print(f"[FAIL] {timeout_s}초 안에 {alias}가 나타나지 않았다", file=sys.stderr)
            return False
        sleep(_POLL_SECONDS)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="wait_model")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)

    def fetch() -> dict:
        with urllib.request.urlopen(f"{args.base_url}/v1/models", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    return 0 if wait_for_alias(fetch, args.alias, args.timeout) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 5d: 테스트가 통과하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/test_wait_model.py -v`
Expected: PASS — 4 passed

- [ ] **Step 6: `start-pi.bat`을 쓴다**

```bat
@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%config.env" call "%ROOT%config.env"
if not defined LLAMA_PORT set "LLAMA_PORT=8080"

set "PI_OFFLINE=1"
set "PI_CODING_AGENT_DIR=%~dp0home\agent"
set "LLAMA_BASE_URL=http://127.0.0.1:%LLAMA_PORT%"

if not exist "%ROOT%bin\pi\pi.exe" (
  echo [FAIL] %ROOT%bin\pi\pi.exe 없음
  exit /b 2
)
if not defined MODEL_ALIAS (
  echo [FAIL] MODEL_ALIAS 미설정 - config.env를 채워라
  exit /b 2
)

call :resolve_python
if errorlevel 1 exit /b 4

%PYTHON_CMD% "%ROOT%tools\wait_model.py" --base-url "%LLAMA_BASE_URL%" --alias "%MODEL_ALIAS%" --timeout 600
if errorlevel 1 (
  echo [FAIL] 모델이 준비되지 않았다 - Pi를 시작하지 않는다
  exit /b 3
)

"%ROOT%bin\pi\pi.exe" --offline --model "%MODEL_ALIAS%" %*
exit /b %errorlevel%

:resolve_python
if defined PYTHON_CMD goto :eof
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3.12"
  goto :eof
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto :eof
)
echo [FAIL] Python을 찾지 못했다 - config.env의 PYTHON_CMD로 경로를 지정하라
exit /b 1
```

- [ ] **Step 7: `tools/verify_bundle.py`를 쓴다**

Task 1의 `manifest.verify`를 그대로 호출한다. 검증 로직을 두 번 구현하지 않기 위해서다. 이 스크립트는 폐쇄망 PC에서 실행되므로 `manifest` 외에는 아무것도 import하지 않는다.

```python
# tools/verify_bundle.py
"""폐쇄망 PC에서 번들이 반입 당시와 같은지 본다.

검증 규칙은 Task 1의 manifest 모듈 하나뿐이다. 여기에 두 번째 구현을 두면
둘이 어긋나도 알 수 없다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="verify_bundle")
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    root = Path(args.root)
    manifest_path = root / "STAGING_MANIFEST.json"
    if not manifest_path.is_file():
        print(f"[FAIL] {manifest_path} 없음", file=sys.stderr)
        return 1
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = manifest.verify(root, document)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"[ok] {document['totals']['files']}개 파일이 매니페스트와 일치한다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 8: `verify-offline.bat`을 쓴다**

```bat
@echo off
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
if exist "%ROOT%config.env" call "%ROOT%config.env"
if not defined LLAMA_PORT set "LLAMA_PORT=8080"
set "EV=%ROOT%evidence"
if not exist "%EV%" mkdir "%EV%"

echo [1/6] 하드웨어와 드라이버
nvidia-smi > "%EV%\nvidia-smi.txt" 2>&1
type "%EV%\nvidia-smi.txt"

echo [2/6] 번들 무결성
call :resolve_python
if errorlevel 1 exit /b 4
%PYTHON_CMD% "%ROOT%tools\verify_bundle.py" --root "%ROOT%" > "%EV%\manifest-check.txt" 2>&1
type "%EV%\manifest-check.txt"

echo [3/6] 네트워크 캡처 시작
pktmon start --capture --file-name "%EV%\pktmon.etl" >nul 2>&1
if errorlevel 1 echo [warn] pktmon을 시작하지 못했다 - 관리자 권한이 필요할 수 있다

echo [4/6] 적재된 모델
powershell -NoProfile -ExecutionPolicy Bypass -Command "(Invoke-RestMethod -Uri 'http://127.0.0.1:%LLAMA_PORT%/v1/models' -TimeoutSec 10) | ConvertTo-Json -Depth 6" > "%EV%\v1-models.json" 2>&1
type "%EV%\v1-models.json"

echo [5/6] Pi 툴 왕복
set "PI_OFFLINE=1"
set "PI_CODING_AGENT_DIR=%ROOT%home\agent"
set "LLAMA_BASE_URL=http://127.0.0.1:%LLAMA_PORT%"
"%ROOT%bin\pi\pi.exe" --offline --no-session --model "%MODEL_ALIAS%" --tools read --mode json -p "evidence\probe.txt 파일을 read 도구로 읽고 그 안의 낱말 하나를 그대로 답하라" > "%EV%\pi-tool-roundtrip.json" 2>&1
type "%EV%\pi-tool-roundtrip.json"

echo [6/6] 네트워크 캡처 종료
pktmon stop >nul 2>&1
pktmon etl2txt "%EV%\pktmon.etl" --out "%EV%\pktmon.txt" >nul 2>&1

echo.
echo 증거는 %EV% 에 있다. 종료 코드가 아니라 그 안의 내용이 판정 기준이다.
echo 확인할 것: nvidia-smi 드라이버 551.61 이상, 매니페스트 일치, v1-models에 %MODEL_ALIAS%,
echo pi-tool-roundtrip.json 안의 실제 도구 실행과 최종 답변, pktmon.txt에 외부 주소 시도 0건.
goto :end

:resolve_python
if defined PYTHON_CMD goto :eof
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3.12"
  goto :eof
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto :eof
)
echo [FAIL] Python을 찾지 못했다 - config.env의 PYTHON_CMD로 경로를 지정하라
exit /b 1

:end
endlocal
```

- [ ] **Step 9: `README-폐쇄망.md`를 쓴다**

```markdown
# 폐쇄망 실행 안내

## 전제
- 관리자 권한 없이 압축 해제만으로 동작한다.
- 이 번들은 한 사용자 계정 전용이다. `home\agent` 에 세션과 툴 출력이 쌓이고 여기에는 작업한 소스 내용이 남는다.

## 순서
1. 번들을 `C:\pi_agent` 로 복사한다.
2. `config.env.example` 을 `config.env` 로 복사하고 `MODEL_FILE`, `MODEL_ALIAS` 를 채운다.
3. `nvidia-smi` 로 GPU별 여유 VRAM을 보고 `GPU_TENSOR_SPLIT` 을 정한다. 비워두면 기본 분배를 쓴다. `1,1,1` 로 고정하지 않는다.
4. 창 하나에서 `start-llama.bat` 을 실행한다. 이 창은 서버가 사는 곳이므로 닫지 않는다.
5. 다른 창에서 `start-pi.bat` 을 실행한다. 모델이 준비되기 전에는 Pi가 뜨지 않는다.
6. `verify-offline.bat` 을 실행해 `evidence\` 에 증거를 남긴다.

## GPU가 안 잡힐 때
- `nvidia-smi` 의 드라이버가 551.61 미만이면 CUDA 12.4 빌드가 동작하지 않는다.
- `config.env` 의 `LLAMA_BACKEND` 를 `vulkan` 또는 `cpu` 로 바꿔 원인을 좁힌다. CPU는 진단용이며 30B 모델 실사용 속도가 나오지 않는다.
- `MSVCP140.dll` 관련 오류가 나면 `bin\llama-cuda` 안의 app-local DLL이 지워졌는지 확인한다.

## 하지 않는 것
- `pi install` 로 패키지나 확장을 설치하지 않는다. npm이 필요하고 폐쇄망에서는 동작하지 않는다.
- 모델을 새로 내려받지 않는다. 반입한 GGUF만 쓴다.
- `--host` 를 `127.0.0.1` 외의 값으로 바꾸지 않는다.
```

- [ ] **Step 10: 테스트가 통과하는지 확인한다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/ -v`
Expected: PASS — 전체 통과 (win 스크립트 10 + wait_model 4 + 앞선 태스크들)

- [ ] **Step 11: 커밋한다**

```bash
cd /mnt/h/model/pi_agent
git add win/ tools/wait_model.py tools/verify_bundle.py tests/test_win_scripts.py tests/test_wait_model.py
git commit -m "폐쇄망 실행 계층을 추가한다 - 모델 준비 전에는 Pi가 뜨지 않는다"
```

---

### Task 7: 모델 선정과 획득

**Files:**
- Create: `/mnt/h/model/pi_agent/models/` (git 무시)
- Modify: `/mnt/h/model/pi_agent/docs/superpowers/specs/2026-08-18-pi-agent-closed-network-design.md` (§6에 확정된 파일명·해시 기록)

**Interfaces:**
- Consumes: `stage.py model-check`, `gguf.check_tool_capable`
- Produces: `models/` 안의 GGUF 두 개와 그 파일명·바이트·SHA256. 이 값들이 `config.env` 의 `MODEL_FILE` 과 Task 9의 매니페스트에 들어간다.

- [ ] **Step 1: 후보 배포판을 조사한다**

Qwen3-Coder-30B-A3B-Instruct의 Q4_K_M GGUF 배포판과 백업용 7~8B 코딩 모델의 Q4_K_M을 찾는다. 각 후보에 대해 파일 크기, 분할 여부(`-00001-of-0000N`), 라이선스를 기록한다. 다중 분할 파일이면 스펙 §4의 `models\` 하위 디렉터리 규칙을 따른다.

- [ ] **Step 2: 주력 모델을 받는다**

```bash
cd /mnt/h/model/pi_agent
mkdir -p models
curl -fL --retry 3 -o "models/<확정된-파일명>.gguf" "<확정된-URL>"
sha256sum models/*.gguf
stat -c '%n %s' models/*.gguf
```

- [ ] **Step 3: 툴 호출 가능성을 검사한다**

Run: `cd /mnt/h/model/pi_agent && python3 tools/stage.py model-check --root .`
Expected: 각 GGUF에 대해 `[ok]`. `tokenizer.chat_template이 없다`가 나오면 그 배포판은 쓰지 않고 Step 1로 돌아간다.

- [ ] **Step 4: 백업 모델도 같은 절차를 밟는다**

7~8B Q4_K_M을 받고 `model-check`를 다시 돌린다. 두 모델 모두 통과해야 한다.

- [ ] **Step 5: 스펙에 확정값을 기록한다**

스펙 §6의 마지막 문단("정확한 GGUF 파일명 ...")을 확정된 파일명·바이트·SHA256·alias 표로 대체한다.

- [ ] **Step 6: 커밋한다**

```bash
cd /mnt/h/model/pi_agent
git add docs/superpowers/specs/2026-08-18-pi-agent-closed-network-design.md
git commit -m "반입할 모델을 확정하고 chat_template을 확인한다"
```

---

### Task 8: 리허설

폐쇄망에서 깨질 것을 인터넷 되는 쪽에서 잡는다. 이 태스크는 윈도우 PC에서 사람이 수행하며, 산출물은 `evidence\rehearsal\` 이다.

**Files:**
- Create: `/mnt/h/model/pi_agent/docs/superpowers/plans/rehearsal-log-2026-08-18.md`

**Interfaces:**
- Consumes: Task 5의 번들, Task 6의 스크립트, Task 7의 모델
- Produces: 리허설 로그와 `config.env` 에 채울 확정값 — `PI_PROVIDER`, 실측 기반 `GPU_TENSOR_SPLIT` 권고값, Pi가 llama.cpp 모델을 부르는 정확한 ID 형식

- [ ] **Step 1: 스테이징을 끝낸다**

```bash
cd /mnt/h/model/pi_agent
python3 tools/stage.py fetch --root . --cache .cache
python3 tools/stage.py layout --root . --cache .cache --vc-source <VC++ DLL이 있는 경로>
cp win/*.bat win/config.env.example win/README-폐쇄망.md ./
python3 tools/stage.py manifest --root . --target "H:\\model\\pi_agent"
```

- [ ] **Step 2: 깨끗한 상태에서 실행한다**

윈도우 PC에서 기존 Pi 흔적을 지우고 시작한다: `%USERPROFILE%\.pi` 가 있으면 다른 이름으로 옮긴다. `config.env` 를 채우고 `start-llama.bat` 을 실행한다. `llama-server` 가 GPU를 잡는지 로그로 확인하고 `evidence\rehearsal\llama-start.txt` 로 남긴다.

- [ ] **Step 3: Pi의 제공자 이름과 모델 ID를 확정한다**

```bat
set PI_OFFLINE=1
set LLAMA_BASE_URL=http://127.0.0.1:8080
bin\pi\pi.exe --offline --list-models > evidence\rehearsal\pi-list-models.txt 2>&1
```

출력에서 llama.cpp 제공자 이름과 모델 ID 형식을 읽어 `config.env` 의 `PI_PROVIDER` 와 `MODEL_ALIAS` 에 반영한다. 여기서 확정하기 전에는 `--model` 인자가 맞는지 알 수 없다.

- [ ] **Step 4: 툴 왕복을 확인한다**

`evidence\probe.txt` 에 낱말 하나를 넣고 `verify-offline.bat` 을 실행한다. `pi-tool-roundtrip.json` 안에 도구 호출과 **실제 실행 결과**, 그리고 그 낱말을 담은 최종 답변이 모두 있어야 한다. 호출 문자열만 생성되고 실행이 없으면 실패로 기록한다.

- [ ] **Step 5: 32k 부하와 GPU 분산을 본다**

컨텍스트 상한에 가까운 프롬프트를 한 번 넣고 생성이 끝까지 가는지 본다. `nvidia-smi` 를 병행 기록해 3장의 VRAM 점유를 남기고, 편중이 있으면 `GPU_TENSOR_SPLIT` 권고값을 계산한다.

- [ ] **Step 6: 오프라인 상태로 다시 돌린다**

NIC를 끄거나 localhost 외 아웃바운드를 차단하고 Step 2~4를 반복한다. **이 조건에서 통과해야 반입 가능이다.** `pktmon.txt` 에서 외부 주소로의 연결 **시도**가 0건인지 확인한다.

- [ ] **Step 7: 백엔드 폴백을 시험한다**

`LLAMA_BACKEND` 를 `vulkan`, `cpu` 로 각각 바꿔 최소한 서버가 뜨고 `/v1/models` 가 응답하는지 확인한다.

- [ ] **Step 8: 리허설 로그를 쓰고 커밋한다**

각 단계의 결과, 실패한 것과 그 대처, `config.env` 확정값을 `docs/superpowers/plans/rehearsal-log-2026-08-18.md` 에 기록한다.

```bash
cd /mnt/h/model/pi_agent
git add docs/superpowers/plans/rehearsal-log-2026-08-18.md win/config.env.example
git commit -m "리허설 결과와 확정된 설정값을 기록한다"
```

---

### Task 9: 최종 스테이징과 반입

**Files:**
- Modify: `/mnt/h/model/pi_agent/STAGING_MANIFEST.json` (재발행)
- Create: `/mnt/h/model/pi_agent/docs/superpowers/plans/handover-2026-08-18.md`

**Interfaces:**
- Consumes: Task 8의 확정값
- Produces: 반입 준비가 끝난 `H:\model\pi_agent` 와 인수인계 문서

- [ ] **Step 1: 가변 영역을 비운다**

리허설 중 쌓인 세션과 증거를 지운다. 반입 번들은 첫 실행 전 상태여야 한다.

```bash
cd /mnt/h/model/pi_agent
rm -rf home evidence
mkdir -p home/agent evidence
```

- [ ] **Step 2: 매니페스트를 재발행한다**

Run: `cd /mnt/h/model/pi_agent && python3 tools/stage.py manifest --root . --target "H:\\model\\pi_agent"`
Expected: `[ok] N files, M bytes` — N에 `bin/`, `models/`, `.bat`, `tools/`, README가 모두 포함된다.

- [ ] **Step 3: 매니페스트를 검증한다**

Run: `cd /mnt/h/model/pi_agent && python3 tools/stage.py verify --root .`
Expected: `[ok] 매니페스트와 일치한다`

- [ ] **Step 4: 전체 테스트를 돌린다**

Run: `cd /mnt/h/model/pi_agent && python3 -m pytest tests/ -v`
Expected: PASS — 전체 통과

- [ ] **Step 5: 인수인계 문서를 쓴다**

`handover-2026-08-18.md` 에 다음을 적는다: 번들 총 용량과 파일 수, `config.env` 에 이미 채워진 값과 현장에서 채워야 할 값, 실패 시 확인 순서(드라이버 → VC 런타임 → 백엔드 폴백 → 모델 alias), 그리고 스펙 §10의 현장 확인 항목 체크리스트.

- [ ] **Step 6: 커밋한다**

```bash
cd /mnt/h/model/pi_agent
git add docs/superpowers/plans/handover-2026-08-18.md
git commit -m "반입 준비를 마치고 인수인계 문서를 남긴다"
```

---

## 계획 자체 점검 결과

- **스펙 커버리지:** §3 사실 → Task 2(해시 핀)·Task 3(백엔드 분리·VC 런타임), §4 레이아웃 → Task 5, §5 부트스트랩 계약 → Task 6(wait_model.py 선행 조건), §6 GPU 배치 → Task 6(인자 고정)·Task 8 Step 5(실측), §7 오프라인 봉인 → Task 6(start-pi.bat)·Task 8 Step 6, §8 검증 → Task 8·Task 6(verify-offline.bat), §9 매니페스트 범위 → Task 1, §10 현장 확인 → Task 9 Step 5. 빠진 절 없음.
- **미확정 표기:** `<확정된-파일명>`, `<확정된-URL>`, `<VC++ DLL이 있는 경로>` 세 곳은 Task 7·8이 산출하는 값의 자리다. 계획 시점에 알 수 없는 값이며 해당 태스크의 산출물로 명시했다.
- **타입 일관성:** `manifest.sha256_of`(Task 1)를 `assets`(Task 2)가 그대로 쓴다. `layout.VC_RUNTIME_DLLS`·`BACKEND_MARKERS`(Task 3)를 `stage._layout`(Task 5)이 간접 사용한다. `config.env` 변수 이름은 Task 6의 세 스크립트와 테스트에서 동일하다.
