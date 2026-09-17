"""tools/export_sessions.py — 승인 세션을 LoRA SFT JSONL로 추출하는 규칙을 고정한다.

핵심 계약은 "학습 샘플 = 추론 때 모델이 받은 입력"이다. pi_session_0851_lora_snapshot.jsonl은 윈도우
pi.exe 0.85.1 + stub 서버로 실제로 만든 세션이고(번들 패키지 전부 + learning.ts + lora-snapshot.ts 적재,
두 번째 실행에서 도구·사고 수준 변경, superpowers가 요청에만 부트스트랩 user 메시지를 끼움), .requests.jsonl은
그때 stub이 받은 요청 body다(tasks/.../artifacts/export-v2-probe/run_full.bat).
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT_SESSION = FIXTURES / "pi_session_0851_lora_snapshot.jsonl"
SNAPSHOT_SESSION_ID = "01a0af3d-bf83-77b5-9a13-538b10ed1683"
SNAPSHOT = {"hash": "h1", "system": "SYSTEM PROMPT", "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "medium"},
            "tools": [{"type": "function", "function": {"name": "read", "description": "Read", "parameters": {"type": "object"}}}]}


def run_tool(sessions_dir, approved_file, out_file, extra_args=None):
    cmd = [sys.executable, "tools/export_sessions.py", "--sessions-dir", str(sessions_dir), "--approved", str(approved_file), "--out", str(out_file)]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))


def samples(out):
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]


def export(tmp_path, entries, sid="s1", extra_args=None):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    with open(sessions / f"{sid}.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "session", "version": 3, "id": sid, "cwd": "C:\\work"}) + "\n")
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    approved = tmp_path / "approved.txt"
    approved.write_text(sid + "\n", encoding="utf-8")
    out = tmp_path / "out.jsonl"
    return run_tool(sessions, approved, out, extra_args), out


def chain(*specs):
    """(type, payload) 목록을 parentId로 한 줄 경로로 잇는다."""
    entries, parent = [], None
    for n, (kind, payload) in enumerate(specs):
        entry = {"type": kind, "id": f"e{n}", "parentId": parent, **payload}
        entries.append(entry)
        parent = entry["id"]
    return entries


def user(text):
    return ("message", {"message": {"role": "user", "content": [{"type": "text", "text": text}]}})


def snap(**overrides):
    return ("custom", {"customType": "lora-request", "data": {**SNAPSHOT, **overrides}})


def assistant(*blocks, stop="stop", tokens=100):
    return ("message", {"message": {"role": "assistant", "content": list(blocks), "stopReason": stop,
                                    "usage": {"totalTokens": tokens}}})


def text(value):
    return {"type": "text", "text": value}


def call(cid, name="read", **arguments):
    return {"type": "toolCall", "id": cid, "name": name, "arguments": arguments}


def result(cid, value):
    return ("message", {"message": {"role": "toolResult", "toolCallId": cid, "toolName": "read",
                                    "content": [text(value)], "isError": False}})


def test_real_pi_session_splits_where_tools_and_effort_changed_and_keeps_injected_messages(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    shutil.copy(SNAPSHOT_SESSION, sessions / "s.jsonl")
    approved = tmp_path / "approved.txt"
    approved.write_text(SNAPSHOT_SESSION_ID + "\n")
    out = tmp_path / "out.jsonl"

    res = run_tool(sessions, approved, out)

    assert res.returncode == 0, res.stderr
    first, second = samples(out)
    assert (first["segment"], first["train_indices"], second["segment"], second["train_indices"]) == (0, [3, 5], 1, [7, 9])
    assert first["chat_template_kwargs"]["reasoning_effort"] == "medium"
    assert second["chat_template_kwargs"]["reasoning_effort"] == "xhigh"
    assert [t["function"]["name"] for t in first["tools"]] == ["read"]
    assert [t["function"]["name"] for t in second["tools"]] == ["read", "bash", "subagent"]
    assert first["messages"][0]["role"] == "system" and first["messages"][0]["content"] != second["messages"][0]["content"]
    assert first["messages"][1]["content"].startswith("<EXTREMELY_IMPORTANT>")  # 세션 파일에는 없는 주입
    read_call = first["messages"][3]
    assert read_call["tool_calls"][0]["function"]["arguments"] == {"path": "C:\\pi-rt-export\\proj\\probe.txt"}
    assert read_call["reasoning_content"] == "파일을 먼저 읽어야 한다."
    assert first["tokens"] == 1010
    # 두 번째 샘플의 앞부분은 첫 실행의 대화 전체다(문맥), 학습 대상은 그 뒤다.
    assert second["messages"][1:6] == first["messages"][1:]


def test_samples_render_exactly_like_the_requests_pi_sent(tmp_path):
    jinja2 = pytest.importorskip("jinja2")
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    shutil.copy(SNAPSHOT_SESSION, sessions / "s.jsonl")
    approved = tmp_path / "approved.txt"
    approved.write_text(SNAPSHOT_SESSION_ID + "\n")
    out = tmp_path / "out.jsonl"
    assert run_tool(sessions, approved, out).returncode == 0

    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    env.globals["raise_exception"] = lambda message: (_ for _ in ()).throw(jinja2.TemplateError(message))
    env.filters["tojson"] = lambda value, **_: json.dumps(value, ensure_ascii=False)
    template = env.from_string((FIXTURES / "qwen38_chat_template.jinja").read_text(encoding="utf-8"))

    def render(messages, tools, kwargs):
        return template.render(messages=messages, tools=tools, add_generation_prompt=True, **kwargs)

    targets = {}
    for sample in samples(out):
        for k, message in enumerate(sample["messages"]):
            if k in sample["train_indices"]:
                targets[(sample["segment"], k)] = render(sample["messages"][:k], sample["tools"], sample["chat_template_kwargs"])

    matched = []
    for line in (FIXTURES / "pi_session_0851_lora_snapshot.requests.jsonl").read_text(encoding="utf-8").splitlines():
        body = json.loads(line)
        for message in body["messages"]:
            for tool_call in message.get("tool_calls") or []:
                tool_call["function"]["arguments"] = json.loads(tool_call["function"]["arguments"])  # llama-server가 하는 일
        rendered = render(body["messages"], body["tools"], body["chat_template_kwargs"])
        hits = [key for key, value in targets.items() if value == rendered]
        assert len(hits) == 1, f"request {len(matched)} matched {hits}"
        matched.append(hits[0])
    assert sorted(matched) == sorted(targets)


def test_sessions_recorded_without_the_snapshot_extension_are_excluded(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    shutil.copy(FIXTURES / "pi_session_0851_stub_roundtrip.jsonl", sessions / "old.jsonl")
    approved = tmp_path / "approved.txt"
    approved.write_text("01a0ad3b-b786-70e1-9111-bc89a86fa274\n")
    out = tmp_path / "out.jsonl"

    res = run_tool(sessions, approved, out)

    assert res.returncode == 3
    assert "요청 스냅샷 없음" in res.stderr
    assert out.read_bytes() == b""
    assert "요청 스냅샷 없음" in out.with_suffix(".report.md").read_text(encoding="utf-8")


def test_unapproved_and_empty_lists(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    shutil.copy(SNAPSHOT_SESSION, sessions / "s.jsonl")
    approved = tmp_path / "approved.txt"
    out = tmp_path / "out.jsonl"

    approved.write_text("nonexistent-id\n")
    assert run_tool(sessions, approved, out).returncode == 2

    approved.write_text("")
    assert run_tool(sessions, approved, out).returncode == 3


def test_missing_id_still_exports_the_rest(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    shutil.copy(SNAPSHOT_SESSION, sessions / "s.jsonl")
    approved = tmp_path / "approved.txt"
    approved.write_text(f"{SNAPSHOT_SESSION_ID}  # 좋은 세션\nmissing-999\n")
    out = tmp_path / "out.jsonl"

    res = run_tool(sessions, approved, out)

    assert res.returncode == 2
    assert "missing-999" in res.stderr
    assert len(samples(out)) == 2


def test_report_carries_the_file_hash_and_unmasked_candidates(tmp_path):
    res, out = export(tmp_path, chain(
        user("C:\\Users\\hong\\repo 에서 10.1.2.3 과 build01.corp.local 확인"), snap(),
        assistant(text("done"))))

    assert res.returncode == 0, res.stderr
    report = out.with_suffix(".report.md").read_text(encoding="utf-8")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    assert digest in report and digest in res.stdout
    assert "`hong`" in report and "`10.1.2.3`" in report and "`build01.corp.local`" in report
    # 가리지 않는다 - 모델이 배울 실제 경로다.
    assert "C:\\Users\\hong\\repo" in samples(out)[0]["messages"][1]["content"]


def test_masking_covers_new_patterns_and_secret_argument_keys(tmp_path):
    github = "ghp_" + "a" * 36
    google = "AIza" + "B" * 35
    res, out = export(tmp_path, chain(
        user(f"token: sk-12345678901234567890 {github} {google} Authorization: Bearer abcdefghijklmnopqrstu"),
        snap(),
        assistant(call("t1", "auth", password="hunter2", url="https://bob:pa55word@git.example.com/x", api_key="AKIA1234567890ABCDEF"), stop="toolUse"),
        result("t1", "-----BEGIN RSA PRIVATE KEY-----\nsecret\n-----END RSA PRIVATE KEY-----"),
        assistant(text("done"))))

    assert res.returncode == 0, res.stderr
    dumped = out.read_text(encoding="utf-8")
    for secret in ("sk-12345678901234567890", github, google, "abcdefghijklmnopqrstu", "hunter2", "pa55word", "AKIA1234567890ABCDEF", "RSA"):
        assert secret not in dumped
    args = samples(out)[0]["messages"][2]["tool_calls"][0]["function"]["arguments"]
    assert args["password"] == "[REDACTED]" and args["url"] == "https://bob:[REDACTED]@git.example.com/x"


def test_thinking_is_kept_by_default_only_when_pi_would_send_it(tmp_path):
    entries = chain(user("q"), snap(), assistant(
        {"type": "thinking", "thinking": "signed", "thinkingSignature": "reasoning_content"}, text("a")))
    res, out = export(tmp_path, entries)
    assert res.returncode == 0
    assert samples(out)[0]["messages"][-1]["reasoning_content"] == "signed"

    res, out = export(tmp_path, entries, extra_args=["--drop-thinking"])
    assert "reasoning_content" not in samples(out)[0]["messages"][-1]

    res, out = export(tmp_path, entries, extra_args=["--keep-thinking"])  # 옛 인자도 받는다
    assert res.returncode == 0

    unsigned = chain(user("q"), snap(), assistant({"type": "thinking", "thinking": "no signature"}, text("a")))
    res, out = export(tmp_path, unsigned)
    assert "reasoning_content" not in samples(out)[0]["messages"][-1]


def test_error_and_aborted_replies_are_dropped_and_orphan_calls_get_synthetic_results(tmp_path):
    res, out = export(tmp_path, chain(
        user("q"), snap(),
        assistant(call("c1"), stop="toolUse"),
        assistant(text("partial"), stop="aborted"),
        user("again"),
        assistant(text("broken"), stop="error"),
        assistant(text("ok"))))

    assert res.returncode == 0, res.stderr
    messages = samples(out)[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "user", "assistant"]
    assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": "No result provided"}
    assert messages[-1]["content"] == "ok"


def test_unfinished_tail_is_cut_and_sessions_without_a_finished_reply_are_excluded(tmp_path):
    res, out = export(tmp_path, chain(user("q"), snap(), assistant(text("a")), user("more"), assistant(call("c9"), stop="toolUse")))
    assert res.returncode == 0
    assert samples(out)[0]["messages"][-1]["content"] == "a"

    res, out = export(tmp_path, chain(user("q"), snap(), assistant(call("c1"), stop="toolUse")))
    assert res.returncode == 3
    assert "완료(stopReason=stop)된 응답 없음" in res.stderr


def test_leaf_branch_is_followed(tmp_path):
    entries = chain(user("q"), snap())
    entries.append({"type": "message", "id": "wrong", "parentId": "e1",
                    "message": {"role": "assistant", "content": [text("wrong")], "stopReason": "stop"}})
    entries.append({"type": "message", "id": "right", "parentId": "e1",
                    "message": {"role": "assistant", "content": [text("right")], "stopReason": "stop"}})
    res, out = export(tmp_path, entries)
    assert [m["content"] for m in samples(out)[0]["messages"][1:]] == ["q", "right"]


def test_compaction_rebuilds_context_like_pi_and_starts_a_new_segment(tmp_path):
    res, out = export(tmp_path, chain(
        user("old"), snap(), assistant(text("old answer")),
        user("kept"), assistant(text("kept answer")),
        ("compaction", {"summary": "SUMMARY", "firstKeptEntryId": "e3", "tokensBefore": 50000}),
        user("new"), assistant(text("new answer"))))

    assert res.returncode == 0, res.stderr
    before, after = samples(out)
    assert [m["content"] for m in before["messages"][1:]] == ["old", "old answer", "kept", "kept answer"]
    assert [m["content"] for m in after["messages"][1:]] == [
        "The conversation history before this point was compacted into the following summary:\n\n<summary>\nSUMMARY\n</summary>",
        "kept", "kept answer", "new", "new answer"]
    assert after["train_indices"] == [5]
    assert before["train_indices"] == [2, 4]


def test_extension_messages_and_user_shell_commands_are_user_turns(tmp_path):
    res, out = export(tmp_path, chain(
        ("custom_message", {"customType": "x", "content": "INJECTED", "display": False}),
        ("message", {"message": {"role": "bashExecution", "command": "dir", "output": "a.txt", "exitCode": 1}}),
        ("message", {"message": {"role": "bashExecution", "command": "secret", "output": "x", "excludeFromContext": True}}),
        ("branch_summary", {"summary": "BRANCH", "fromId": "e0"}),
        user("q"), snap(), assistant(text("a"))))

    assert res.returncode == 0, res.stderr
    contents = [m["content"] for m in samples(out)[0]["messages"] if m["role"] == "user"]
    assert contents == [
        "INJECTED",
        "Ran `dir`\n```\na.txt\n```\n\nCommand exited with code 1",
        "The following is a summary of a branch that this conversation came back from:\n\n<summary>\nBRANCH</summary>",
        "q"]


def test_images_exclude_the_session(tmp_path):
    res, out = export(tmp_path, chain(
        ("message", {"message": {"role": "user", "content": [text("see"), {"type": "image", "data": "AA", "mimeType": "image/png"}]}}),
        snap(), assistant(text("a"))))
    assert res.returncode == 3
    assert "이미지 포함" in res.stderr


def test_malformed_session_is_reported_not_crashed(tmp_path):
    res, out = export(tmp_path, [{"type": "message", "id": "1", "parentId": None, "message": 123}])
    assert res.returncode == 3
    assert "message가 객체가 아님" in res.stderr


def test_truncated_length_replies_stay_as_context_but_are_not_trained(tmp_path):
    res, out = export(tmp_path, chain(user("q"), snap(), assistant(text("cut off"), stop="length"), user("go on"), assistant(text("full"))))
    assert res.returncode == 0, res.stderr
    sample = samples(out)[0]
    assert [m["content"] for m in sample["messages"][1:]] == ["q", "cut off", "go on", "full"]
    assert sample["train_indices"] == [4]


def test_injected_messages_go_where_the_request_had_them(tmp_path):
    res, out = export(tmp_path, chain(user("q"), snap(injected=[{"index": 1, "content": "BOOT"}]), assistant(text("a"))))
    assert res.returncode == 0, res.stderr
    sample = samples(out)[0]
    assert [m["content"] for m in sample["messages"]] == ["SYSTEM PROMPT", "BOOT", "q", "a"]
    assert sample["train_indices"] == [3]

    res, out = export(tmp_path, chain(user("q"), snap(injected=[{"index": 9, "content": "BOOT"}]), assistant(text("a"))))
    assert res.returncode == 3
    assert "주입 메시지 위치" in res.stderr


def test_replies_from_another_model_send_thinking_as_plain_text(tmp_path):
    other = ("message", {"message": {"role": "assistant", "model": "old-model", "stopReason": "stop", "content": [
        {"type": "thinking", "thinking": "old thought", "thinkingSignature": "reasoning_content"}, text("old answer")]}})
    res, out = export(tmp_path, chain(user("q1"), other, user("q2"), snap(model="qwen3.8-27b"),
                                      ("message", {"message": {"role": "assistant", "model": "qwen3.8-27b", "stopReason": "stop", "content": [
                                          {"type": "thinking", "thinking": "new thought", "thinkingSignature": "reasoning_content"}, text("new")]}})))
    assert res.returncode == 0, res.stderr
    old, new = [m for m in samples(out)[0]["messages"] if m["role"] == "assistant"]
    assert old == {"role": "assistant", "content": "old thoughtold answer"}
    assert new["reasoning_content"] == "new thought"


def test_non_object_tool_arguments_exclude_the_session(tmp_path):
    bad = {"type": "toolCall", "id": "c1", "name": "read", "arguments": '{"path": "a.txt"}'}
    res, out = export(tmp_path, chain(user("q"), snap(), assistant(bad, stop="toolUse"), result("c1", "x"), assistant(text("a"))))
    assert res.returncode == 3
    assert "도구 인자가 객체가 아님" in res.stderr


def test_quoted_and_non_string_secrets_are_fully_masked(tmp_path):
    res, out = export(tmp_path, chain(
        user('password="hello world" and secret: \'two words\''), snap(),
        assistant(call("c1", "auth", password=123456, api_keys=["sk-in-a-list"], token={"type": "string"}), stop="toolUse"),
        result("c1", "ok"), assistant(text("a"))))
    assert res.returncode == 0, res.stderr
    dumped = out.read_text(encoding="utf-8")
    for secret in ("hello", "world", "two words", "123456", "sk-in-a-list"):
        assert secret not in dumped
    args = samples(out)[0]["messages"][2]["tool_calls"][0]["function"]["arguments"]
    assert args == {"password": "[REDACTED]", "api_keys": ["[REDACTED]"], "token": {"type": "string"}}


def test_broken_parent_links_are_excluded_not_looped(tmp_path):
    looped = [{"type": "message", "id": "a", "parentId": "a", "message": {"role": "user", "content": "q"}}]
    res, out = export(tmp_path, looped)
    assert res.returncode == 3 and "parentId 순환" in res.stderr

    orphan = [{"type": "message", "id": "a", "parentId": "token=abcdef", "message": {"role": "user", "content": "q"}}]
    res, out = export(tmp_path, orphan)
    assert res.returncode == 3 and "부모 엔트리 없음" in res.stderr
    assert "abcdef" not in res.stderr and "abcdef" not in out.with_suffix(".report.md").read_text(encoding="utf-8")


def test_empty_approval_list_clears_a_previous_export(tmp_path):
    res, out = export(tmp_path, chain(user("q"), snap(), assistant(text("a"))))
    assert res.returncode == 0 and out.read_bytes()

    (tmp_path / "approved.txt").write_text("# 전부 취소\n", encoding="utf-8")
    res = run_tool(tmp_path / "sessions", tmp_path / "approved.txt", out)
    assert res.returncode == 3
    assert out.read_bytes() == b""
    assert "승인 목록이 비었다" in out.with_suffix(".report.md").read_text(encoding="utf-8")


def test_export_wrapper_passes_through_and_documents_the_report():
    body = (ROOT / "win" / "export-sessions.bat").read_text(encoding="ascii")
    assert '--out "%ROOT%lora\\train.jsonl" %*' in body
    assert "train.report.md" in body
    assert (ROOT / "export-sessions.bat").read_bytes() == (ROOT / "win" / "export-sessions.bat").read_bytes()
