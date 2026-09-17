import sys
import json
import pytest
import subprocess
from pathlib import Path

# 도구 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent / 'tools'))

def run_tool(sessions_dir, approved_file, out_file, extra_args=None):
    cmd = [sys.executable, "tools/export_sessions.py", "--sessions-dir", str(sessions_dir), "--approved", str(approved_file), "--out", str(out_file)]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent.parent))

def test_export_fixture_roundtrip(tmp_path):
    # 기본 fixture 정상 내보내기 테스트
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    
    import shutil
    fixture_path = Path(__file__).parent / "fixtures" / "pi_session_0851_stub_roundtrip.jsonl"
    shutil.copy(fixture_path, sessions_dir / "test1.jsonl")
    
    approved = tmp_path / "approved.txt"
    approved.write_text("01a0ad3b-b786-70e1-9111-bc89a86fa274\n")
    
    out = tmp_path / "out.jsonl"
    res = run_tool(sessions_dir, approved, out)
    
    assert res.returncode == 0
    lines = out.read_text().strip().split('\n')
    assert len(lines) == 1
    sample = json.loads(lines[0])
    
    assert sample["session_id"] == "01a0ad3b-b786-70e1-9111-bc89a86fa274"
    msgs = sample["messages"]
    assert len(msgs) == 4
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert "tool_calls" in msgs[1]
    assert msgs[2]["role"] == "tool"
    assert msgs[3]["role"] == "assistant"
    assert msgs[3]["content"] == "NARWHAL-7Q2X"

def test_export_unapproved(tmp_path):
    # 승인 목록에 없으면 내보내지 않고 exit 3
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    
    fixture_path = Path(__file__).parent / "fixtures" / "pi_session_0851_stub_roundtrip.jsonl"
    import shutil
    shutil.copy(fixture_path, sessions_dir / "test1.jsonl")
    
    approved = tmp_path / "approved.txt"
    approved.write_text("nonexistent-id\n")
    
    out = tmp_path / "out.jsonl"
    res = run_tool(sessions_dir, approved, out)
    assert res.returncode == 2 # missing id -> 2
    
    approved.write_text("")
    res = run_tool(sessions_dir, approved, out)
    assert res.returncode == 3 # empty approved list -> 3

def test_export_error_stop_reason(tmp_path):
    # stopReason이 error인 경우 제외
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    
    lines = Path(__file__).parent.joinpath("fixtures", "pi_session_0851_stub_roundtrip.jsonl").read_text().split('\n')
    # 마지막 entry의 stopReason을 error로 변경
    import json
    last = json.loads(lines[-2])
    last["message"]["stopReason"] = "error"
    lines[-2] = json.dumps(last)
    
    (sessions_dir / "err.jsonl").write_text('\n'.join(lines))
    approved = tmp_path / "approved.txt"
    approved.write_text("01a0ad3b-b786-70e1-9111-bc89a86fa274\n")
    
    out = tmp_path / "out.jsonl"
    res = run_tool(sessions_dir, approved, out)
    
    assert res.returncode == 3 # 1개 제외되어 0개 내보내짐 -> 3
    assert "stopReason이 error" in res.stderr

def test_missing_id(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    
    fixture_path = Path(__file__).parent / "fixtures" / "pi_session_0851_stub_roundtrip.jsonl"
    import shutil
    shutil.copy(fixture_path, sessions_dir / "test1.jsonl")
    
    approved = tmp_path / "approved.txt"
    approved.write_text("01a0ad3b-b786-70e1-9111-bc89a86fa274\nmissing-999\n")
    
    out = tmp_path / "out.jsonl"
    res = run_tool(sessions_dir, approved, out)
    
    assert res.returncode == 2
    assert "missing-999" in res.stderr
    
    lines = out.read_text().strip().split('\n')
    assert len(lines) == 1

def test_masking(tmp_path):
    # 비밀 마스킹 검증
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    
    session = [
        {"type":"session","id":"mask-test"},
        {"type":"message","id":"1","parentId":None,"message":{"role":"user","content":[{"type":"text","text":"My password: 'secret123'"}]}},
        {"type":"message","id":"2","parentId":"1","message":{"role":"assistant","content":[{"type":"toolCall","id":"t1","name":"auth","arguments":{"api_key":"AKIA1234567890ABCDEF"}}],"stopReason":"toolUse"}},
        {"type":"message","id":"3","parentId":"2","message":{"role":"toolResult","toolCallId":"t1","content":[{"type":"text","text":"token: sk-12345678901234567890\n-----BEGIN RSA PRIVATE KEY-----\nsecret\n-----END RSA PRIVATE KEY-----"}]}},
        {"type":"message","id":"4","parentId":"3","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"stopReason":"stop"}}
    ]
    
    with open(sessions_dir / "mask.jsonl", "w") as f:
        for s in session:
            f.write(json.dumps(s) + "\n")
            
    approved = tmp_path / "approved.txt"
    approved.write_text("mask-test\n")
    out = tmp_path / "out.jsonl"
    
    res = run_tool(sessions_dir, approved, out)
    assert res.returncode == 0
    
    out_data = json.loads(out.read_text())
    msgs = out_data["messages"]
    
    assert "secret123" not in json.dumps(msgs)
    assert "AKIA1234567890ABCDEF" not in json.dumps(msgs)
    assert "sk-12345678901234567890" not in json.dumps(msgs)
    assert "[REDACTED]" in msgs[0]["content"]
    
    tool_args = json.loads(msgs[1]["tool_calls"][0]["function"]["arguments"])
    assert tool_args["api_key"] == "[REDACTED]"
    
    assert "[REDACTED]" in msgs[2]["content"]
    assert "RSA" not in msgs[2]["content"]

def test_synthetic_branches_and_thinking(tmp_path):
    # 가지 치기 및 thinking 보존 검증
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    
    session = [
        {"type":"session","id":"branch-test"},
        {"type":"message","id":"1","parentId":None,"message":{"role":"user","content":[{"type":"text","text":"q"}]}},
        {"type":"message","id":"2a","parentId":"1","message":{"role":"assistant","content":[{"type":"text","text":"wrong"}],"stopReason":"stop"}},
        {"type":"message","id":"2b","parentId":"1","message":{"role":"assistant","content":[{"type":"thinking","thinking":"think"},{"type":"text","text":"correct"}],"stopReason":"stop"}}
    ]
    
    with open(sessions_dir / "branch.jsonl", "w") as f:
        for s in session:
            f.write(json.dumps(s) + "\n")
            
    approved = tmp_path / "approved.txt"
    approved.write_text("branch-test\n")
    out = tmp_path / "out.jsonl"
    
    # 기본: thinking 제거
    res = run_tool(sessions_dir, approved, out)
    assert res.returncode == 0
    msgs = json.loads(out.read_text())["messages"]
    assert len(msgs) == 2
    assert msgs[1]["content"] == "correct"
    assert "reasoning_content" not in msgs[1]
    
    # --keep-thinking
    res = run_tool(sessions_dir, approved, out, ["--keep-thinking"])
    assert res.returncode == 0
    msgs = json.loads(out.read_text())["messages"]
    assert msgs[1]["content"] == "correct"
    assert msgs[1]["reasoning_content"] == "think"

def test_string_content_and_exception(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    
    # s-str: String content user message & correct thinking block
    session1 = [
        {"type":"session","id":"s-str"},
        {"type":"message","id":"1","parentId":None,"message":{"role":"user","content":"string content"}},
        {"type":"message","id":"2","parentId":"1","message":{"role":"assistant","content":[{"type":"thinking","thinking":"think_text"}],"stopReason":"stop"}}
    ]
    with open(sessions_dir / "s-str.jsonl", "w") as f:
        for s in session1: f.write(json.dumps(s) + "\n")
        
    # s-bad: Message is not a dict
    session2 = [
        {"type":"session","id":"s-bad"},
        {"type":"message","id":"1","parentId":None,"message": 123}
    ]
    with open(sessions_dir / "s-bad.jsonl", "w") as f:
        for s in session2: f.write(json.dumps(s) + "\n")
        
    approved = tmp_path / "approved.txt"
    approved.write_text("s-str\ns-bad\n")
    out = tmp_path / "out.jsonl"
    
    res = run_tool(sessions_dir, approved, out, ["--keep-thinking"])
    assert res.returncode == 0
    assert "제외됨 s-bad: 예외 발생 - message is not a dictionary" in res.stderr
    
    msgs = json.loads(out.read_text())["messages"]
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "string content"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["reasoning_content"] == "think_text"
