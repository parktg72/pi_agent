"""home\\agent\\settings.json에 컨텍스트 때문에 작업이 멈추지 않을 하한을 보장한다.

Pi 0.85.1이 긴 작업을 멈추는 경로를 소스에서 추적했다(2026-09-17).

1. 압축 판정은 `contextTokens > contextWindow - reserveTokens`다
   (dist/core/compaction/compaction.js shouldCompact). contextTokens는 마지막 응답의
   실제 usage에 그 뒤 메시지를 글자수/4로 추정해 더한다 - 한글 도구 결과는 Qwen
   토크나이저에서 글자당 토큰이 훨씬 많아 크게 과소추정된다. 기본 reserveTokens
   16384는 사고 토큰과 답변, 그 추정 오차를 함께 담기에 좁다.
2. 초과·잘림 복구(압축 후 재시도)는 한 실행에 한 번뿐이고, 두 번째부터는
   "Context overflow recovery failed..."로 멈춘다(dist/core/agent-session.js).
3. httpIdleTimeoutMs 기본은 300000(5분)이다(docs/settings.md). llama.cpp b11010은
   스트리밍에서 prompt 처리를 시작할 때 헤더만 보내고 첫 토큰까지 본문을 보내지
   않는다(server-context.cpp:3422). 1080 Ti x3에서 27B의 긴 prefill은 5분을 넘을
   수 있다.
4. retry.provider.timeoutMs가 없으면 OpenAI SDK 기본 10분(DEFAULT_TIMEOUT=6e5)이다.
   --parallel 1이라 다른 요청 뒤에 줄을 서면 헤더 전에 그 시간을 다 쓸 수 있다.

그래서 매 실행마다 네 값의 **하한**(reserveTokens는 창 절반의 상한도)을 맞춘다. settings.json은 운영자가 /settings로
고치는 파일이라 덮어쓰지 않는다 - 더 큰 값, 다른 키, 운영자가 끈 유휴 타임아웃(0)은
그대로 둔다. 하한보다 작은 값만 올리고, 무엇을 바꿨는지 출력한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 번들 내장 임베디드 파이썬은 스크립트 디렉터리를 sys.path에 넣지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_parse import _check_context, write_atomic

# Pi docs/settings.md의 keepRecentTokens 기본값. 키가 없으면 이것이 적용된다.
PI_DEFAULT_KEEP_RECENT = 20000
IDLE_TIMEOUT_FLOOR_MS = 30 * 60 * 1000
PROVIDER_TIMEOUT_FLOOR_MS = 60 * 60 * 1000


def floors(ctx: int, reserve: int | None = None) -> dict[str, int]:
    """창 크기에서 하한을 계산한다. reserve를 주면 그 값으로 keepRecent 상한을 잡는다."""
    reserve_floor = max(8192, ctx * 3 // 8 // 256 * 256)
    # 창의 절반을 넘는 reserve는 압축 임계를 창의 절반 아래로 끌어내려 매 턴 압축을 부른다.
    reserve_ceiling = max(reserve_floor, ctx // 2)
    effective_reserve = min(reserve_ceiling, max(reserve_floor, reserve or 0))
    return {
        "reserveTokens": reserve_floor,
        "reserveTokensMax": reserve_ceiling,
        # 압축 뒤 원문 그대로 남는 최근 이력의 상한. Pi는 이것도 chars/4로 재므로 한글
        # 도구 결과(한 개 최대 50KB, truncate.js)면 실제 토큰이 약 3배일 수 있다. 1/3로
        # 두면 3배 과소추정이어도 재시도 요청이 창 안에 남는다 - 초과 복구는 한 실행에
        # 한 번뿐이라 재시도가 또 넘치면 작업이 멈춘다(agy 리뷰).
        "keepRecentTokensMax": max(4096, (ctx - effective_reserve) // 3),
        "httpIdleTimeoutMs": IDLE_TIMEOUT_FLOOR_MS,
        "providerTimeoutMs": PROVIDER_TIMEOUT_FLOOR_MS,
    }


def _show(value: object) -> str:
    return "(없음)" if value is None else repr(value)


def apply(settings: dict, ctx: int) -> tuple[dict, list[str]]:
    """(갱신된 설정, 바꾼 항목 설명). 입력 dict를 그 자리에서 고친다."""
    changes: list[str] = []
    if not isinstance(settings.get("compaction", {}), dict):
        changes.append(f"compaction: {_show(settings['compaction'])} -> 객체")
        settings["compaction"] = {}
    compaction = settings.setdefault("compaction", {})
    base = floors(ctx, compaction.get("reserveTokens") if isinstance(compaction.get("reserveTokens"), int) else None)

    if compaction.get("enabled") is not True:
        changes.append(f"compaction.enabled: {_show(compaction.get('enabled'))} -> True")
        compaction["enabled"] = True

    reserve = compaction.get("reserveTokens")
    if not isinstance(reserve, int) or reserve < base["reserveTokens"]:
        changes.append(f"compaction.reserveTokens: {_show(reserve)} -> {base['reserveTokens']}")
        compaction["reserveTokens"] = base["reserveTokens"]
    elif reserve > base["reserveTokensMax"]:
        changes.append(f"compaction.reserveTokens: {_show(reserve)} -> {base['reserveTokensMax']}")
        compaction["reserveTokens"] = base["reserveTokensMax"]

    keep = compaction.get("keepRecentTokens")
    if "keepRecentTokens" in compaction and not (isinstance(keep, int) and not isinstance(keep, bool) and keep > 0):
        # 음수·0·문자열·소수는 Pi로 넘기지 않는다(opencode 리뷰).
        replacement = min(PI_DEFAULT_KEEP_RECENT, base["keepRecentTokensMax"])
        changes.append(f"compaction.keepRecentTokens: {_show(keep)} -> {replacement}")
        compaction["keepRecentTokens"] = replacement
    else:
        effective_keep = keep if isinstance(keep, int) else PI_DEFAULT_KEEP_RECENT
        if effective_keep > base["keepRecentTokensMax"]:
            changes.append(f"compaction.keepRecentTokens: {_show(keep)} -> {base['keepRecentTokensMax']}")
            compaction["keepRecentTokens"] = base["keepRecentTokensMax"]

    idle = settings.get("httpIdleTimeoutMs")
    if not (isinstance(idle, int) and (idle == 0 or idle >= base["httpIdleTimeoutMs"])):
        changes.append(f"httpIdleTimeoutMs: {_show(idle)} -> {base['httpIdleTimeoutMs']}")
        settings["httpIdleTimeoutMs"] = base["httpIdleTimeoutMs"]

    if not isinstance(settings.get("retry", {}), dict):
        changes.append(f"retry: {_show(settings['retry'])} -> 객체")
        settings["retry"] = {}
    retry = settings.setdefault("retry", {})
    if not isinstance(retry.get("provider", {}), dict):
        changes.append(f"retry.provider: {_show(retry['provider'])} -> 객체")
        retry["provider"] = {}
    provider = retry.setdefault("provider", {})
    timeout = provider.get("timeoutMs")
    if not (isinstance(timeout, int) and timeout >= base["providerTimeoutMs"]):
        changes.append(f"retry.provider.timeoutMs: {_show(timeout)} -> {base['providerTimeoutMs']}")
        provider["timeoutMs"] = base["providerTimeoutMs"]
    return settings, changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi_settings", description=__doc__)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--ctx", required=True)
    arguments = parser.parse_args(argv)

    reason = _check_context(arguments.ctx)
    if reason:
        print(f"[FAIL] LLAMA_CTX={arguments.ctx} - {reason}", file=sys.stderr)
        return 1
    ctx = int(arguments.ctx)

    current: dict = {}
    if arguments.settings.is_file():
        try:
            current = json.loads(arguments.settings.read_text(encoding="utf-8-sig"))
        except ValueError as error:
            print(f"[FAIL] {arguments.settings}가 JSON이 아니다 - 고치거나 지운 뒤 다시 실행하라: {error}", file=sys.stderr)
            return 1
        if not isinstance(current, dict):
            print(f"[FAIL] {arguments.settings}의 최상위가 객체가 아니다", file=sys.stderr)
            return 1

    updated, changes = apply(current, ctx)
    if not changes and arguments.settings.is_file():
        print(f"[ok] settings.json 컨텍스트 안전값 유지(LLAMA_CTX {ctx})")
        return 0
    try:
        write_atomic(arguments.settings, json.dumps(updated, indent=2, ensure_ascii=True) + "\n")
    except OSError as error:
        print(f"[FAIL] {arguments.settings}를 쓰지 못했다: {error}", file=sys.stderr)
        return 1
    for change in changes:
        print(f"[info] settings.json {change}")
    print(f"[ok] settings.json 컨텍스트 안전값 적용(LLAMA_CTX {ctx})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
