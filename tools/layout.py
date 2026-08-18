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
