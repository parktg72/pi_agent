"""PI_SUBAGENT_TOOLS=0일 때 운영자가 start-pi.bat에 준 인자가 스위치와 부딪치는지 본다.

스위치는 pi.exe에 `--exclude-tools subagent,bg_wait,subagent_supervisor`를 붙인다
(tasks/pi-agent-subagents-switch 합의). Pi 0.85.1은 `--exclude-tools`를 두 번 받으면
**마지막 것만** 적용한다(2026-10-02 번들 pi.exe + 모의 서버 실측) - 운영자가 뒤에 자기
제외 목록을 주면 세 도구가 조용히 되살아난다. 두 목록을 배치에서 합치려면 인자를 다시
조립해야 하므로 합치지 않고 기동을 거부한다.

옵션 종료 `--` 뒤는 프롬프트라 보지 않는다. 다만 `--`가 다른 옵션의 값일 수 있다
(`--append-system-prompt "--" --exclude-tools read`에서 Pi는 `--`를 값으로 먹고 뒤의 제외
목록을 적용한다 - codex R3이 pi.exe의 parseArgs로 확인). Pi의 옵션별 인자 개수를 여기서
따라 하지 않고, `-`로 시작하는 인자 바로 뒤의 `--`는 값일 수 있다고 보고 계속 본다. 그래서
거부는 보수적이다: `--` 앞에서는 다른 옵션의 값으로 준 같은 문자열도, 값 없는 옵션 바로
뒤의 진짜 `--` 다음에 온 같은 문자열도 거부한다.

인자를 배치의 for로 쪼개지 않고 여기서 argv로 받는 이유: for는 쉼표·세미콜론·등호에서
쪼개고 와일드카드를 파일 이름으로 펼친다.
"""
from __future__ import annotations

import sys

EXCLUDE_FLAGS = ("--exclude-tools", "-xt")


def clash(arguments: list[str]) -> str | None:
    """부딪치는 인자를 돌려준다. 없으면 None."""
    for index, argument in enumerate(arguments):
        if argument == "--":
            previous = arguments[index - 1] if index else ""
            if previous.startswith("-") and previous != "--":
                continue  # 앞 옵션의 값일 수 있다
            return None
        if argument in EXCLUDE_FLAGS or argument.startswith(tuple(flag + "=" for flag in EXCLUDE_FLAGS)):
            return argument
    return None


def main(argv: list[str]) -> int:
    found = clash(argv)
    if found is None:
        return 0
    print(
        f"[FAIL] PI_SUBAGENT_TOOLS=0인데 인자에 {found}가 있다 - Pi는 --exclude-tools를 마지막 것만 "
        "적용해서 subagent 도구가 다시 켜진다",
        file=sys.stderr,
    )
    print(
        "[FAIL] 자기 제외 목록을 쓰면서 subagent 도구도 끄려면: config.env에서 PI_SUBAGENT_TOOLS=1로 두고 "
        "그 목록에 subagent,bg_wait,subagent_supervisor를 직접 더한다",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
