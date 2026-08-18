"""번들이 싣고 온 패키지 목록과 대상 PC의 settings.json 목록을 대조한다.

`home\\agent\\settings.json`은 사용자가 `/trust`, `/settings`로 직접 고칠 수
있는 파일이라 `start-pi.bat`이 **없을 때만** 심는다(선점 위험 없음은 실측으로
확인됐다). 문제는 갱신 경로다 — v2 번들이 패키지를 추가해도 기존
`settings.json`이 있으면 조용히 미등록되고, `xcopy /D`는 상류에서 삭제된
파일을 지우지 않는다. 즉 어긋남을 감지할 수단이 하나도 없다.

그래서 여기서는 **경고만 한다.** 자동으로 덮어쓰지 않는다: 운영자가 편집할 수
있는 파일이고, 편집을 되돌리는 것은 이 스크립트가 낼 판단이 아니다. 종료
코드는 언제나 0이다 — 이 대조 때문에 Pi 기동이 막히면 안 된다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _packages(path: Path) -> list[str] | None:
    """읽을 수 없거나 형식이 아니면 None. 없는 파일과 깨진 파일을 구분하지 않는다."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    packages = document.get("packages") if isinstance(document, dict) else None
    return [str(entry) for entry in packages] if isinstance(packages, list) else None


def compare(bundled: list[str] | None, installed: list[str] | None) -> list[str]:
    """운영자에게 보여 줄 경고 줄. 같으면 빈 목록."""
    if bundled is None:
        return ["[warn] 번들의 settings.packages.json을 읽지 못해 패키지 목록을 대조하지 못했다"]
    if installed is None:
        # 아직 심어지기 전이거나(최초 실행) 사용자가 packages 항목을 지웠다.
        # 전자는 정상 경로라 조용히 넘어간다 - 호출자가 파일 존재를 먼저 본다.
        return []
    missing = [name for name in bundled if name not in installed]
    extra = [name for name in installed if name not in bundled]
    if not missing and not extra:
        return []
    lines = ["[warn] home\\agent\\settings.json의 패키지 목록이 번들과 다르다 - 자동으로 고치지 않는다"]
    for name in missing:
        lines.append(f"        번들에만 있음(미등록): {name}")
    for name in extra:
        lines.append(f"        settings.json에만 있음: {name}")
    lines.append("        번들 목록으로 되돌리려면 home\\agent\\settings.json을 지우고 다시 실행하라.")
    lines.append("        직접 고친 설정이 있으면 그 파일의 packages 배열만 손으로 맞춰라.")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundled", required=True, type=Path)
    parser.add_argument("--installed", required=True, type=Path)
    arguments = parser.parse_args(argv)

    for line in compare(_packages(arguments.bundled), _packages(arguments.installed)):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
