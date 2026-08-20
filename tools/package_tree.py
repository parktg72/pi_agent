"""반입한 패키지 트리와 대상 트리를 경로·크기·해시로 통째로 대조한다.

2026-08-19 외부 감사(GPT-5.6 Sol) 지적: 동기화 게이트가 앵커 파일 두 개
(`npm\\node_modules\\pi-subagents\\package.json`,
`git\\github.com\\obra\\superpowers\\package.json`)만 확인했다. xcopy가 개별
파일에서 접근 거부로 실패해도 종료 코드 0을 내는 사례가 이미 실측돼 있으므로
(2026-08-18), 앵커 하나만 남으면 **부분 실패가 통과**한다. 확장 하나가 파일
절반만 놓인 채 로드되면 그 실패는 Pi 안에서 나타나고 배치는 조용하다.

그래서 staged 트리 전체를 대상 트리와 대조한다. 2,191 파일 14MB이므로 해시까지
계산해도 싸다 - 크기만 비교하면 같은 크기로 잘린 전송을 놓친다.

2026-08-20 재리뷰(GPT-5.6 Sol)에서 이 대상-only 경고 처리 자체가 NOT ADDRESSED로
남았다: `xcopy /D`는 상류에서 삭제된 파일을 지우지 않으므로, 번들을 갱신해
패키지 하나를 뺐는데도 구버전 잔여 파일이 대상에 남으면 이 검사는 그것을 그냥
통과시킨다 - "실어 온 것이 그대로 놓였는가"의 반대 방향은 아무도 보지 않았다.

"Pi 자신이 이 트리 밑에 쓸 수도 있다"는 가설은 실측으로 반증됐다(2026-08-20,
WSL cmd.exe): 빈 npm\\, git\\ 아래에서 `pi.exe list`를 실행하고, 실제
반입본을 그대로 복사한 npm\\, git\\ 트리를 대상으로 `pi.exe list`와 오프라인
tool-roundtrip 시도(`--tools read --mode json -p ...`)까지 실행했다. 두
경우 모두 실행 전후 트리가 바이트 단위로 동일했다(`package_tree.py` 자체로
재대조, 전량 일치). Pi가 실제로 새로 쓰는 파일은 `auth.json`,
`models-store.json`이며 - 이번 실측에서도 `settings.json`과 함께 - 셋 다
`PI_CODING_AGENT_DIR` **바로 밑**에만 생겼고, 이 모듈이 대조하는 `npm\\`,
`git\\` 서브트리 안에는 하나도 생기지 않았다. 그 세 파일은 애초에 이 모듈의
`--pair` 인자 범위 밖이다(호출부는 `npm::...`, `git::...` 쌍만 넘긴다).

그래서 대상에만 있는 파일도 이제 **실패**로 다룬다 - 빠진 파일·내용이 다른
파일과 같은 자격이다. 폐쇄망 고정 번들이 대상인 만큼 좁은 예외보다 엄격한
양방향 일치가 맞다. 새 패키지 버전으로 갱신하면서 옛 파일이 지워지지 않은
채 반입되는 사고를 이 검사가 막는다.
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
    # 2026-08-20까지는 이것이 warnings였다 - "Pi 자신이 여기 쓸 수도 있다"는
    # 가설 때문이었다. 실측(위 docstring)으로 반증됐으므로 이제 failures다.
    failures += [f"대상에만 있음: {relative}" for relative in sorted(set(placed) - set(staged))]
    warnings: list[str] = []

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
