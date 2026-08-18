"""반입한 파이썬 스택이 실제로 임포트되는지 패키지마다 한 줄씩 기록한다.

`install-python-packages.bat`이 설치 직후 호출한다. 핵심 다섯 개만 한 번에
임포트하던 이전 방식은 lightgbm·catboost·shap·pyarrow·pyreadstat·seaborn·
sksurv가 깨져 있어도 증거가 초록이었다 — 한 줄로 묶어 임포트하면 어느 것이
실패했는지도 알 수 없다. 그래서 `requirements.txt`가 선언한 **직접 의존
전부**를 하나씩, 각각 독립적으로 임포트하고 성공/실패를 개별 줄로 남긴다.
하나라도 실패하면 그 사실이 증거 파일에 그대로 드러난다.

배포 이름과 임포트 이름은 같지 않다(scikit-learn -> sklearn, pyyaml -> yaml,
python-docx -> docx, scikit-survival -> sksurv). 기본 규칙은 하이픈을
밑줄로 바꾸는 것이고, 어긋나는 것만 IMPORT_NAMES에 적는다. 목록에 없는
배포가 requirements.txt에 새로 생기면 기본 규칙으로 시도하고, 그것이 실패하면
"기본 규칙으로 유추했다"고 그 줄에 적는다 — 조용히 건너뛰지 않는다.
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
import traceback
from pathlib import Path

# 배포 이름 -> 임포트할 모듈. 기본 규칙(하이픈->밑줄, 소문자)과 다른 것만 적는다.
# 값이 점을 포함하면 그 하위 모듈까지 임포트한다 - 최상위 패키지만 임포트하면
# 네이티브 확장이 로드되지 않아 아무것도 증명하지 못하는 경우가 있다.
IMPORT_NAMES = {
    "scikit-learn": "sklearn",
    "scikit-survival": "sksurv",
    "python-docx": "docx",
    "python-dotenv": "dotenv",
    "pyyaml": "yaml",
    "statsmodels": "statsmodels.api",
    "matplotlib": "matplotlib.pyplot",
}

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def requirement_names(text: str) -> list[str]:
    """requirements.txt에서 직접 의존의 배포 이름만 순서대로 뽑는다."""
    names: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _NAME.match(line)
        if not match:
            continue
        name = match.group(0)
        if name not in names:
            names.append(name)
    return names


def module_for(distribution: str) -> tuple[str, bool]:
    """(임포트할 모듈 이름, 표에 명시돼 있었는가)."""
    key = distribution.lower()
    if key in IMPORT_NAMES:
        return IMPORT_NAMES[key], True
    return key.replace("-", "_"), False


def _version_of(module) -> str:
    root = sys.modules.get(module.__name__.split(".", 1)[0], module)
    return str(getattr(root, "__version__", "") or "?")


def check(distribution: str) -> tuple[bool, str]:
    module_name, mapped = module_for(distribution)
    try:
        module = importlib.import_module(module_name)
    except BaseException:  # noqa: BLE001 - SystemExit을 내는 상류 패키지도 실패로 센다
        kind, value, _ = sys.exc_info()
        reason = " ".join(traceback.format_exception_only(kind, value)).strip().replace("\n", " ")
        # 성공한 줄에는 유추 여부를 적지 않는다 - 임포트가 됐다는 것이 이름이
        # 맞았다는 증거다. 실패한 줄에만 적는다: 표에 없는 이름을 기본 규칙으로
        # 유추한 것이 실패의 원인일 수 있고, 그때 볼 곳이 IMPORT_NAMES다.
        suffix = "" if mapped else "  (임포트 이름을 기본 규칙으로 유추했다 - IMPORT_NAMES 확인)"
        return False, f"FAIL  {distribution:<18} import {module_name:<20} {reason}{suffix}"
    return True, f"OK    {distribution:<18} import {module_name:<20} {_version_of(module)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", required=True, type=Path)
    arguments = parser.parse_args(argv)

    # 임포트 검사 때문에 창이 뜨거나 백엔드 선택이 실패하지 않게 한다.
    os.environ.setdefault("MPLBACKEND", "Agg")

    names = requirement_names(arguments.requirements.read_text(encoding="utf-8"))
    print(f"python {sys.version.splitlines()[0]}")
    print(f"executable {sys.executable}")
    print(f"requirements {arguments.requirements}")
    print("-" * 72)

    failures = 0
    for name in names:
        ok, line = check(name)
        failures += 0 if ok else 1
        print(line, flush=True)

    print("-" * 72)
    print(f"SUMMARY total={len(names)} ok={len(names) - failures} fail={failures}")
    if failures:
        print("IMPORT_FAILED - 위 FAIL 줄이 설치가 끝나지 않았거나 DLL이 없다는 뜻이다")
        return 1
    print("IMPORT_OK - 직접 의존 전부가 임포트됐다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
