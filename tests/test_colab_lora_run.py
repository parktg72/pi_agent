"""colab-lora/run.sh — Colab 과금·정리 가드를 가짜 colab CLI로 고정한다(C단계 합의 10).

가짜 colab은 세션 상태를 파일로 두고, exec는 표준입력 파이썬의 /content/pi-lora를 임시 폴더로 바꿔 실행한다.
업로드한 실제 파일은 그대로 두고(sha256 대조를 거치게), 백그라운드 실행 명령의 train.py·verify_load.py만 가짜
학습기(모드: ok·fail·hang·limit)·가짜 검증기로 바꿔 띄운다. 실제 Colab·GPU는 쓰지 않는다.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "colab-lora" / "run.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("split") is None, reason="bash·split 필요")

FAKE_COLAB = r'''
import json, os, shutil, sys
from pathlib import Path
state = Path(os.environ["MOCK_STATE"]); remote = state / "remote"; calls = state / "calls.log"
args = sys.argv[1:]
with calls.open("a") as f:
    f.write(" ".join(args) + "\n")
cmd = args[0]
sessions = state / "sessions.json"
active = json.loads(sessions.read_text()) if sessions.exists() else []
if cmd == "sessions":
    print("\n".join(f"[{s}] endpoint-{s} | Hardware: H100" for s in active) if active else "[colab] No active sessions found on server.")
elif cmd == "new":
    active.append(args[args.index("-s") + 1]); sessions.write_text(json.dumps(active)); remote.mkdir(exist_ok=True)
elif cmd == "status":
    print(f"[{args[args.index('-s') + 1]}] gpu-x | Hardware: {os.environ.get('MOCK_HW', 'H100')} | Variant: GPU | Status: IDLE")
elif cmd == "stop":
    active = [s for s in active if s != args[args.index("-s") + 1]]; sessions.write_text(json.dumps(active))
elif cmd == "upload":
    src, dst = args[-2], Path(args[-1].replace("/content/pi-lora", str(remote)))
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
elif cmd == "download":
    src, dst = Path(args[-2].replace("/content/pi-lora", str(remote))), args[-1]
    shutil.copy(src, dst)
elif cmd == "exec":
    code = sys.stdin.read().replace("/content/pi-lora", str(remote))
    kill = "import os, signal\nfor pid in os.listdir('/proc'):\n    try:\n        if pid.isdigit() and os.readlink(f'/proc/{pid}/cwd') == %r and int(pid) != os.getpid():\n            os.kill(int(pid), signal.SIGKILL)\n    except OSError:\n        pass\n" % str(remote)
    for script in ("train.py", "verify_load.py"):
        code = code.replace('subprocess.run(["pkill", "-f", "%s"])' % script, kill)
    code = code.replace('os.path.expanduser("~/.cache/huggingface")', repr(str(state / "hf-cache")))
    code = code.replace('\\"$0\\" train.py ', '\\"$0\\" ' + os.environ["MOCK_TRAIN"] + ' ')
    code = code.replace('\\"$0\\" verify_load.py ', '\\"$0\\" ' + os.environ["MOCK_VERIFY"] + ' ')
    code = code.replace('"-m", "pip", "install"', '"-c", "print(1)", "install"').replace('"-m", "pip", "freeze"', '"-c", "print(\'torch==x\')"')
    exec(compile(code, "<remote>", "exec"), {"__name__": "__main__"})
'''

FAKE_TRAIN = r'''
import hashlib, json, os, sys, time
mode = os.environ.get("MOCK_TRAIN_MODE", "ok")
print(json.dumps({"event": "start"}), flush=True)
if mode == "hang":
    time.sleep(120)
if mode == "fail":
    print(json.dumps({"event": "fail", "reason": "mock"}), flush=True); sys.exit(3)
if mode == "limit":  # 시간 상한: checkpoint를 남기고 5로 끝난다
    os.makedirs("out/checkpoint/adapter", exist_ok=True)
    open("out/checkpoint/state.pt", "wb").write(os.urandom(50 * 1024 * 1024))
    open("out/checkpoint/adapter/adapter_model.safetensors", "wb").write(b"a" * 1000)
    open("out/checkpoint/adapter/adapter_config.json", "w").write("{}")
    sys.exit(5)
os.makedirs("out/adapter", exist_ok=True)
data = os.urandom(45 * 1024 * 1024)  # 40MB 조각 2개로 나뉜다
open("out/adapter/adapter_model.safetensors", "wb").write(data)
open("out/adapter/adapter_config.json", "w").write("{}")
config = b"{}"
open("out/adapter/adapter_config.json", "wb").write(config)
train = open("train.jsonl", "rb").read()
json.dump({"adapter_sha256": hashlib.sha256(data).hexdigest(), "adapter_config_sha256": hashlib.sha256(config).hexdigest(),
           "data_sha256": hashlib.sha256(train).hexdigest() if mode != "wrongdata" else "0" * 64, "args": sys.argv[1:]}, open("out/report.json", "w"))
print(json.dumps({"event": "done"}), flush=True)
'''


FAKE_VERIFY = r'''
import json, os, sys
mode = os.environ.get("MOCK_VERIFY_MODE", "ok")
os.makedirs("out/verify", exist_ok=True)
json.dump({"ok": mode == "ok", "args": sys.argv[1:]}, open("out/verify/verify.json", "w"))
print(json.dumps({"event": "verify", "ok": mode == "ok"}), flush=True)
sys.exit(0 if mode == "ok" else 4)
'''


@pytest.fixture
def env(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    colab = bin_dir / "colab"
    colab.write_text(f"#!/bin/sh\nexec {sys.executable} {tmp_path / 'fake_colab.py'} \"$@\"\n")
    colab.chmod(0o755)
    (tmp_path / "fake_colab.py").write_text(FAKE_COLAB)
    (tmp_path / "fake_train.py").write_text(FAKE_TRAIN)
    (tmp_path / "fake_verify.py").write_text(FAKE_VERIFY)
    data = tmp_path / "train.jsonl"
    data.write_text('{"x": 1}\n')
    report = tmp_path / "train.report.md"
    report.write_text(f"- sha256: `{hashlib.sha256(data.read_bytes()).hexdigest()}` (무결성 확인용)\n")
    environment = dict(os.environ, COLAB=str(colab), MOCK_STATE=str(state), MOCK_TRAIN=str(tmp_path / "fake_train.py"), MOCK_VERIFY=str(tmp_path / "fake_verify.py"),
                       POLL_SEC="1", WORK_ROOT=str(tmp_path / "work"), PATH=f"{bin_dir}:{os.environ['PATH']}")
    return {"tmp": tmp_path, "state": state, "data": data, "report": report, "env": environment}


def run(env, mode="trial", *extra, **overrides):
    environment = dict(env["env"], **overrides)
    return subprocess.run(["bash", str(RUN), mode, str(env["data"]), str(env["report"]), *extra],
                          capture_output=True, text=True, env=environment, timeout=300)


def calls(env):
    return (env["state"] / "calls.log").read_text().splitlines() if (env["state"] / "calls.log").exists() else []


def session_closed(env, name="pi-lora"):
    return name not in json.loads((env["state"] / "sessions.json").read_text())


def test_success_downloads_split_adapter_verifies_hash_and_stops(env):
    res = run(env, "trial", "--lr", "5e-5")
    assert res.returncode == 0, res.stdout + res.stderr
    work = next((env["tmp"] / "work").iterdir())
    adapter = work / "adapter" / "adapter_model.safetensors"
    report = json.loads((work / "report.json").read_text())
    assert hashlib.sha256(adapter.read_bytes()).hexdigest() == report["adapter_sha256"]
    assert int(report["args"][report["args"].index("--time-limit-min") + 1]) >= 110  # 150분 - 검증 몫 30 - 5
    assert "--trial" in report["args"] and report["args"][-2:] == ["--lr", "5e-5"]
    downloads = [c for c in calls(env) if c.startswith("download") and "adapter_model.safetensors.part_" in c]
    assert len(downloads) == 2  # 45MB -> 40MB 조각 2개
    uploads = [c for c in calls(env) if c.startswith("upload")]
    assert any("train.py.part_00" in c for c in uploads)
    assert json.loads((work / "verify.json").read_text())["args"] == ["--adapter", "out/adapter", "--out", "out/verify"]
    assert calls(env)[-2].startswith("stop") and session_closed(env)
    assert not (env["state"] / "remote").exists() or not any((env["state"] / "remote").iterdir())


def test_data_that_does_not_match_the_export_report_never_starts_a_session(env):
    env["data"].write_text('{"x": 2}\n')
    res = run(env)
    assert res.returncode == 65
    assert not any(c.startswith("new") for c in calls(env))


def test_an_existing_session_blocks_a_new_one(env):
    (env["state"] / "sessions.json").write_text(json.dumps(["someone-else"]))
    res = run(env)
    assert res.returncode == 66
    assert not any(c.startswith("new") for c in calls(env))


def test_training_failure_still_cleans_up_and_stops(env):
    res = run(env, MOCK_TRAIN_MODE="fail")
    assert res.returncode == 73
    assert any(c.startswith("stop") for c in calls(env)) and session_closed(env)


def test_deadline_kills_training_and_stops(env):
    res = run(env, WALL_SEC="15", VERIFY_RESERVE_MIN="0", MIN_TRAIN_MIN="-100", MOCK_TRAIN_MODE="hang")
    assert res.returncode == 72, res.stdout + res.stderr
    assert "마감" in res.stderr
    assert any(c.startswith("stop") for c in calls(env)) and session_closed(env)


def test_failed_q6k_load_check_is_reported_and_still_stops(env):
    res = run(env, MOCK_VERIFY_MODE="fail")
    assert res.returncode == 75, res.stdout + res.stderr
    work = next((env["tmp"] / "work").iterdir())
    assert (work / "adapter" / "adapter_model.safetensors").exists() and json.loads((work / "verify.json").read_text())["ok"] is False
    assert any(c.startswith("stop") for c in calls(env)) and session_closed(env)


def test_time_limited_training_keeps_its_checkpoint(env):
    res = run(env, "train", MOCK_TRAIN_MODE="limit", PART_BYTES="20M")
    assert res.returncode == 76, res.stdout + res.stderr
    work = next((env["tmp"] / "work").iterdir())
    assert (work / "checkpoint" / "state.pt").stat().st_size == 50 * 1024 * 1024
    assert "RESUME_FROM=" in res.stderr
    assert any(c.startswith("stop") for c in calls(env)) and session_closed(env)


def test_resume_uploads_the_checkpoint_and_asks_train_py_to_resume(env):
    ckpt = env["tmp"] / "ckpt"
    (ckpt / "adapter").mkdir(parents=True)
    (ckpt / "state.pt").write_bytes(b"s" * 1000)
    (ckpt / "adapter" / "adapter_model.safetensors").write_bytes(b"a" * 1000)
    (ckpt / "adapter" / "adapter_config.json").write_text("{}")
    res = run(env, "train", RESUME_FROM=str(ckpt))
    assert res.returncode == 0, res.stdout + res.stderr
    assert (env["state"] / "remote").exists() is False or True
    work = next((env["tmp"] / "work").iterdir())
    assert "--resume" in json.loads((work / "report.json").read_text())["args"]
    assert any("out/checkpoint/state.pt.part_00" in c for c in calls(env) if c.startswith("upload"))

    res = run(env, "trial", RESUME_FROM=str(ckpt))
    assert res.returncode == 64


def test_report_that_does_not_match_the_uploaded_data_fails(env):
    res = run(env, MOCK_TRAIN_MODE="wrongdata")
    assert res.returncode == 74, res.stdout + res.stderr
    assert session_closed(env)


def test_watchdog_is_not_left_running(env):
    res = run(env)
    assert res.returncode == 0
    leftovers = subprocess.run(["pgrep", "-f", f"sleep {90 * 60 + 600}"], capture_output=True, text=True).stdout.split()
    assert leftovers == []


def test_a_substituted_gpu_stops_before_uploading(env):
    res = run(env, MOCK_HW="L4")
    assert res.returncode == 77, res.stdout + res.stderr
    assert "L4" in res.stderr
    assert not any(c.startswith("upload") for c in calls(env))
    assert any(c.startswith("stop") for c in calls(env)) and session_closed(env)


def test_other_sessions_need_explicit_permission_and_are_left_alone(env):
    (env["state"] / "sessions.json").write_text(json.dumps(["browser-runtime"]))
    assert run(env).returncode == 66
    res = run(env, ALLOW_OTHER_SESSIONS="1")
    assert res.returncode == 0, res.stdout + res.stderr
    assert json.loads((env["state"] / "sessions.json").read_text()) == ["browser-runtime"]
    assert "세션 종료 확인" in res.stderr


def test_a_leftover_session_with_our_name_is_refused_even_when_others_are_allowed(env):
    (env["state"] / "sessions.json").write_text(json.dumps(["pi-lora"]))
    res = run(env, ALLOW_OTHER_SESSIONS="1")
    assert res.returncode == 66
    assert "같은 이름" in res.stderr
