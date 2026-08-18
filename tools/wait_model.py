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
) -> bool:
    # elapsed는 실제 시계가 아니라 sleep 호출 누적으로 잰다. sleep만 주입해도
    # 테스트가 실제로 기다리지 않게 하려면, 시간의 경과를 실제 시계(time.monotonic)가
    # 아니라 주입된 sleep 호출 그 자체로 정의해야 한다.
    elapsed = 0.0
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
        if elapsed + _POLL_SECONDS > timeout_s:
            print(f"[FAIL] {timeout_s}초 안에 {alias}가 나타나지 않았다", file=sys.stderr)
            return False
        sleep(_POLL_SECONDS)
        elapsed += _POLL_SECONDS


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
