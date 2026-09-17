"""lora-snapshot 확장의 번들 배선과 계약을 고정한다.

동작 자체(요청마다 조건이 바뀔 때만 기록, 기록값 == stub이 받은 요청)는 윈도우 pi.exe 0.85.1 실측으로
확인했고(tasks/.../artifacts/export-v2-probe), 그 세션이 test_export_sessions.py의 고정 자료다.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "win"
EXTENSION = (WIN / "pi-extensions" / "lora-snapshot.ts").read_text(encoding="utf-8")
LOAD_LEARNING = 'if exist "%ROOT%pi-extensions\\learning.ts" set EXT_ARG=--extension "%ROOT%pi-extensions\\learning.ts"'
LOAD_SNAPSHOT = 'if exist "%ROOT%pi-extensions\\lora-snapshot.ts" set EXT_ARG=%EXT_ARG% --extension "%ROOT%pi-extensions\\lora-snapshot.ts"'


@pytest.mark.parametrize("name", ["start-pi.bat", "verify-offline.bat"])
def test_scripts_load_it_after_learning_and_before_launch(name):
    lines = (WIN / name).read_text(encoding="ascii").splitlines()
    launch = next(i for i, line in enumerate(lines) if line.startswith('"%ROOT%bin\\pi\\pi.exe" --offline'))
    assert lines.index(LOAD_LEARNING) < lines.index(LOAD_SNAPSHOT) < launch
    assert "%EXT_ARG%" in lines[launch]


@pytest.mark.parametrize("name", ["start-pi.bat", "verify-offline.bat", "pi-extensions/lora-snapshot.ts"])
def test_staged_copies_match_the_win_sources(name):
    assert (ROOT / name).read_bytes() == (WIN / name).read_bytes()


@pytest.mark.parametrize(
    "needle",
    [
        'const SNAPSHOT_TYPE = "lora-request";',  # tools/export_sessions.py SNAPSHOT_TYPE와 같아야 한다
        'pi.on("before_provider_request"',  # 확장이 바꾼 뒤의 실제 요청 body를 본다
        "!sessionManager.isPersisted()",  # --no-session(verify-offline)에서는 기록하지 않는다
        "if (entry.data?.hash === hash) return;",  # 현재 가지의 마지막 기록과 같으면 다시 쓰지 않는다
        "} catch {",  # 기록 실패로 요청을 막지 않는다
        "injected.push({ index, content: text });",  # 세션에서 유도되지 않는 user 메시지(superpowers 부트스트랩 등)
        'model: typeof payload?.model === "string" ? payload.model : null,',  # 다른 모델 응답의 thinking 처리
    ],
)
def test_extension_keeps_its_contract(needle):
    assert needle in EXTENSION


def test_exporter_reads_the_same_entry_type_and_summary_wording():
    exporter = (ROOT / "tools" / "export_sessions.py").read_text(encoding="utf-8")
    assert 'SNAPSHOT_TYPE = "lora-request"' in exporter
    for name in ("BRANCH_SUMMARY_PREFIX", "BRANCH_SUMMARY_SUFFIX", "COMPACTION_SUMMARY_PREFIX", "COMPACTION_SUMMARY_SUFFIX"):
        ts_value = next(line for line in EXTENSION.splitlines() if line.startswith(f"const {name} = ")).split(" = ", 1)[1].rstrip(";")
        py_value = next(line for line in exporter.splitlines() if line.startswith(f"{name} = ")).split(" = ", 1)[1]
        assert ts_value == py_value, name
