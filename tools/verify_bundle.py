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
