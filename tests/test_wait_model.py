import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import wait_model


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

    slept = []
    assert wait_model.wait_for_alias(fetch, "target", timeout_s=100, sleep=slept.append) is True
    assert len(slept) == 2, "필요한 만큼만 기다려야 한다"


def test_returns_false_when_the_alias_never_appears():
    def fetch():
        return {"data": [{"id": "other-model"}]}

    elapsed = []

    def sleep(seconds):
        elapsed.append(seconds)
        if len(elapsed) > 50:
            raise AssertionError("타임아웃이 걸리지 않았다")

    assert wait_model.wait_for_alias(fetch, "target", timeout_s=10, sleep=sleep) is False


def test_a_server_that_never_answers_times_out_rather_than_hanging():
    def fetch():
        raise ConnectionError("서버 없음")

    assert wait_model.wait_for_alias(fetch, "target", timeout_s=10, sleep=lambda _: None) is False


def test_a_malformed_payload_is_treated_as_not_ready():
    def fetch():
        return {"unexpected": "shape"}

    assert wait_model.wait_for_alias(fetch, "target", timeout_s=5, sleep=lambda _: None) is False
