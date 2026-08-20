"""반입한 패키지 트리와 대상 트리를 경로·크기·해시로 통째로 대조한다.

2026-08-19 외부 감사(GPT-5.6 Sol) 지적: 동기화 게이트가 앵커 파일 두 개
(`npm\\node_modules\\pi-subagents\\package.json`,
`git\\github.com\\obra\\superpowers\\package.json`)만 확인했다. xcopy가 개별
파일에서 접근 거부로 실패해도 종료 코드 0을 내는 사례가 이미 실측돼 있으므로
(2026-08-18), 앵커 하나만 남으면 **부분 실패가 통과**한다. 확장 하나가 파일
절반만 놓인 채 로드되면 그 실패는 Pi 안에서 나타나고 배치는 조용하다.

그래서 staged 트리 전체를 대상 트리와 대조한다. 2,191 파일 14MB이므로 해시까지
계산해도 싸다 - 크기만 비교하면 같은 크기로 잘린 전송을 놓친다.

대상에만 있는 파일은 **경고**로 남긴다. `xcopy /D`는 상류에서 삭제된 파일을
지우지 않고, `home\\agent\\`는 매니페스트 밖 가변 영역이라 Pi 자신이 무언가를
쓸 수도 있다. 빠진 파일과 내용이 다른 파일만 실패로 다룬다 - 그것이 "실어 온
것이 그대로 놓였는가"라는 질문의 답이다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manifest import sha256_of


def _relative_files(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file():
            found[path.relative_to(root).as_posix()] = path
    return found


def compare_trees(source: Path, destination: Path) -> tuple[list[str], list[str]]:
    """(실패, 경고). 실패가 비어 있을 때만 트리가 그대로 놓인 것이다."""
    if not source.is_dir():
        return ([f"원본 트리가 없다: {source}"], [])
    if not destination.is_dir():
        return ([f"대상 트리가 없다: {destination}"], [])

    staged = _relative_files(source)
    placed = _relative_files(destination)

    failures = [f"놓이지 않음: {relative}" for relative in sorted(set(staged) - set(placed))]
    warnings = [f"대상에만 있음: {relative}" for relative in sorted(set(placed) - set(staged))]

    for relative in sorted(set(staged) & set(placed)):
        left, right = staged[relative], placed[relative]
        if left.stat().st_size != right.stat().st_size:
            failures.append(f"크기 다름: {relative}")
        elif sha256_of(left) != sha256_of(right):
            failures.append(f"내용 다름: {relative}")
    return failures, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="package_tree", description=__doc__)
    parser.add_argument(
        "--pair",
        action="append",
        required=True,
        metavar="SOURCE::DESTINATION",
        help="대조할 트리 쌍. 여러 번 줄 수 있다.",
    )
    parser.add_argument("--max-report", type=int, default=20)
    arguments = parser.parse_args(argv)

    total_failures: list[str] = []
    for pair in arguments.pair:
        if "::" not in pair:
            print(f"[FAIL] --pair는 SOURCE::DESTINATION 형식이다: {pair}", file=sys.stderr)
            return 2
        source_text, destination_text = pair.split("::", 1)
        source, destination = Path(source_text), Path(destination_text)
        failures, warnings = compare_trees(source, destination)
        for warning in warnings[: arguments.max_report]:
            print(f"[warn] {source.name}: {warning}")
        if len(warnings) > arguments.max_report:
            print(f"[warn] {source.name}: 그 외 {len(warnings) - arguments.max_report}건 더")
        for failure in failures[: arguments.max_report]:
            print(f"[FAIL] {source.name}: {failure}", file=sys.stderr)
        if len(failures) > arguments.max_report:
            print(
                f"[FAIL] {source.name}: 그 외 {len(failures) - arguments.max_report}건 더",
                file=sys.stderr,
            )
        if not failures:
            print(f"[ok] {source} -> {destination} 전량 일치")
        total_failures += failures

    if total_failures:
        print(
            f"[FAIL] 패키지 트리가 반입본과 다르다({len(total_failures)}건) - "
            "확장이 절반만 놓인 채로 Pi를 띄우지 않는다",
            file=sys.stderr,
        )
        # xcopy /D는 대상이 원본보다 새로우면 건너뛴다(2026-08-19 윈도우 실측).
        # 즉 손상된 대상 파일은 다시 실행해도 저절로 고쳐지지 않는다.
        print(
            "        대상 트리를 통째로 지우고 다시 실행하면 반입본에서 다시 채워진다 - "
            "xcopy /D는 대상이 더 새로우면 건너뛰므로 재실행만으로는 고쳐지지 않는다.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
