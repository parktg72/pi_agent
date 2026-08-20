"""툴 왕복 판정이 실제 실패를 실패로 부르는지 본다.

2026-08-19 감사에서 Pi는 `stopReason: error` / `Connection error.`를 내고도
배치가 `EXITCODE=0`이었다. 여기 픽스처는 그 상황을 포함한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import tool_roundtrip

PROBE = "NARWHAL-7Q2X"

GOOD = """{"type":"tool_execution_start","toolCall":{"name":"read","arguments":{"path":"C:\\\\pi_agent\\\\evidence\\\\probe.txt"}}}
{"type":"tool_execution_end","isError":false,"result":"NARWHAL-7Q2X"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"NARWHAL-7Q2X"}]},"stopReason":"stop","usage":{"inputTokens":812,"outputTokens":14}}
"""

# 같은 내용을 snake_case로 낸 백엔드. 스키마 이름을 하나로 고정하지 않았다는
# 사실 자체를 지키는 픽스처다.
GOOD_SNAKE = """{"event":"tool_call","tool_name":"read"}
{"event":"tool_result","is_error":false,"output":"NARWHAL-7Q2X"}
{"role":"assistant","content":"NARWHAL-7Q2X","stop_reason":"stop","usage":{"input_tokens":5,"output_tokens":2}}
"""


def test_a_complete_round_trip_has_no_problems():
    problems, facts = tool_roundtrip.judge(GOOD, PROBE)
    assert problems == []
    assert facts["stop_reasons"] == ["stop"]
    assert facts["tokens"] > 0
    assert facts["final_text"].strip() == PROBE


def test_the_same_events_in_snake_case_also_pass():
    problems, _ = tool_roundtrip.judge(GOOD_SNAKE, PROBE)
    assert problems == []


def test_a_connection_error_is_a_failure():
    # 감사가 재현한 그 출력이다.
    events = (
        '{"type":"assistant","message":{"role":"assistant","content":""},'
        '"stopReason":"error","error":"Connection error.","usage":{"inputTokens":0,"outputTokens":0}}\n'
    )
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert any("stopReason" in problem for problem in problems)


def test_a_file_that_is_not_json_is_a_failure():
    problems, facts = tool_roundtrip.judge("Connection error.\nretrying...\n", PROBE)
    assert problems and facts == {}


def test_an_empty_file_is_a_failure():
    problems, _ = tool_roundtrip.judge("", PROBE)
    assert problems


def test_zero_tokens_is_a_failure():
    events = GOOD.replace('"inputTokens":812,"outputTokens":14', '"inputTokens":0,"outputTokens":0')
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert any("토큰" in problem for problem in problems)


def test_no_token_report_at_all_is_a_failure():
    events = GOOD.replace(',"usage":{"inputTokens":812,"outputTokens":14}', "")
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert any("토큰" in problem for problem in problems)


def test_a_missing_tool_call_is_a_failure():
    events = "\n".join(GOOD.splitlines()[1:])
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert any("도구 호출" in problem for problem in problems)


def test_a_missing_tool_result_is_a_failure():
    lines = GOOD.splitlines()
    events = "\n".join([lines[0], lines[2]])
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert any("도구 결과" in problem for problem in problems)


def test_a_tool_error_is_a_failure():
    events = GOOD.replace('"isError":false', '"isError":true')
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert any("오류" in problem for problem in problems)


def test_an_answer_without_the_probe_word_is_a_failure():
    # 모델이 파일을 못 읽고 그럴듯하게 지어낸 경우다.
    events = GOOD.replace('"text":"NARWHAL-7Q2X"', '"text":"I read the file."')
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert any(PROBE in problem for problem in problems)


def test_an_empty_final_answer_is_a_failure():
    events = GOOD.replace('[{"type":"text","text":"NARWHAL-7Q2X"}]', '[]')
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert any("assistant" in problem for problem in problems)


def test_a_missing_stop_reason_is_a_failure():
    events = GOOD.replace('"stopReason":"stop",', "")
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert any("stopReason" in problem for problem in problems)


def test_main_returns_zero_only_for_a_complete_round_trip(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(GOOD, encoding="utf-8")
    assert tool_roundtrip.main(["--events", str(good), "--expect", PROBE]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(GOOD.replace('"stopReason":"stop"', '"stopReason":"error"'), encoding="utf-8")
    assert tool_roundtrip.main(["--events", str(bad), "--expect", PROBE]) == 1

    assert tool_roundtrip.main(["--events", str(tmp_path / "nope.json"), "--expect", PROBE]) == 1


def test_a_single_pretty_printed_document_is_read_too(tmp_path):
    # JSON Lines가 아니라 통짜 배열/객체로 내는 빌드도 있다.
    events = "[\n" + ",\n".join(GOOD.strip().splitlines()) + "\n]\n"
    problems, _ = tool_roundtrip.judge(events, PROBE)
    assert problems == []
