import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import wait_model


def fake_clock():
    """(now, sleep) 쌍. sleep이 시계를 전진시키므로 실제로 기다리지 않는다."""
    clock = [0.0]

    def now():
        return clock[0]

    def sleep(seconds):
        clock[0] += seconds

    return now, sleep


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

    now, tick = fake_clock()
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        tick(seconds)

    assert wait_model.wait_for_alias(fetch, "target", timeout_s=100, sleep=sleep, now=now) is True
    assert len(slept) == 2, "필요한 만큼만 기다려야 한다"


def test_returns_false_when_the_alias_never_appears():
    def fetch():
        return {"data": [{"id": "other-model"}]}

    now, sleep = fake_clock()
    assert wait_model.wait_for_alias(fetch, "target", timeout_s=10, sleep=sleep, now=now) is False


def test_a_server_that_never_answers_times_out_rather_than_hanging():
    def fetch():
        raise ConnectionError("서버 없음")

    now, sleep = fake_clock()
    assert wait_model.wait_for_alias(fetch, "target", timeout_s=10, sleep=sleep, now=now) is False


def test_a_malformed_payload_is_treated_as_not_ready():
    def fetch():
        return {"unexpected": "shape"}

    now, sleep = fake_clock()
    assert wait_model.wait_for_alias(fetch, "target", timeout_s=5, sleep=sleep, now=now) is False


def test_slow_fetch_calls_count_against_the_timeout():
    """느린 fetch도 마감에 반영돼야 한다 - sleep 호출 횟수만으로 경과를 세면 안 된다.

    urlopen(timeout=10)처럼 fetch 자체가 오래 걸리면, 그 시간이 빠진 채 sleep
    호출만 세는 구현은 명목 timeout_s를 실측으로 몇 배 넘길 수 있다(리뷰에서
    지적된 결함). now()가 벽시계를 매번 다시 읽어야 fetch 소요 시간도 마감
    판정에 들어간다.
    """
    now, tick = fake_clock()

    def fetch():
        tick(4.0)  # 매 fetch가 4초 걸린다고 가정
        return {"data": [{"id": "other-model"}]}

    slept = []

    def sleep(seconds):
        slept.append(seconds)
        tick(seconds)

    # _POLL_SECONDS(5초)짜리 폴링 두 번(fetch 4초 + sleep 5초)이면 이미 9초가
    # 지나므로, timeout_s=12에서는 두 번째 fetch 이후 한 번만 sleep하고 끝나야
    # 한다. fetch 시간을 무시하는 구현이라면 훨씬 더 오래(더 많은 sleep) 돈다.
    assert wait_model.wait_for_alias(fetch, "target", timeout_s=12, sleep=sleep, now=now) is False
    assert len(slept) == 1, "fetch 소요 시간이 마감 판정에 반영되어야 한다"
