"""home\\agent\\settings.json의 컨텍스트 안전값 하한을 실제 값으로 검사한다.

근거(Pi 0.85.1 소스, 2026-09-17):
- dist/core/compaction/compaction.js shouldCompact: contextTokens > contextWindow - reserveTokens.
  마지막 응답의 실제 usage + 그 뒤 메시지를 chars/4로 추정한다 - 한글 도구 결과는 과소추정된다.
- dist/core/agent-session.js: 초과·잘림 복구(압축 후 재시도)는 한 실행에 한 번뿐이다.
- docs/settings.md: httpIdleTimeoutMs 기본 300000(5분), retry.provider.timeoutMs 미설정 시 SDK 기본
  (OpenAI SDK DEFAULT_TIMEOUT=6e5, 10분).
- llama.cpp b11010 server-context.cpp:3422: 스트리밍은 prompt 처리 시작에 헤더만 보내고 첫 토큰까지
  본문이 없다 - 1080 Ti x3에서 긴 prefill이 5분 유휴 타임아웃을 넘을 수 있다.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pi_settings


def test_floors_scale_with_the_context():
    floors = pi_settings.floors(63488)
    assert floors["reserveTokens"] == 23808  # 63488 * 3 / 8, 256 단위 내림
    assert floors["keepRecentTokensMax"] == (63488 - 23808) // 3
    assert floors["httpIdleTimeoutMs"] == 1_800_000
    assert floors["providerTimeoutMs"] == 3_600_000
    small = pi_settings.floors(32768)
    assert small["reserveTokens"] == 12288
    assert small["keepRecentTokensMax"] == (32768 - 12288) // 3


def test_an_empty_settings_file_gets_every_safety_value():
    result, changes = pi_settings.apply({}, 63488)
    assert result["compaction"] == {"enabled": True, "reserveTokens": 23808, "keepRecentTokens": (63488 - 23808) // 3}
    assert result["httpIdleTimeoutMs"] == 1_800_000
    assert result["retry"]["provider"]["timeoutMs"] == 3_600_000
    assert changes


def test_other_user_keys_survive_and_larger_values_are_kept():
    settings = {
        "packages": ["npm:pi-subagents@0.68.0"],
        "theme": "dark",
        "compaction": {"reserveTokens": 30000, "keepRecentTokens": 10000},
        "httpIdleTimeoutMs": 7_200_000,
        "retry": {"maxRetries": 5, "provider": {"timeoutMs": 9_000_000, "maxRetries": 0}},
    }
    result, changes = pi_settings.apply(json.loads(json.dumps(settings)), 63488)
    assert result["packages"] == settings["packages"] and result["theme"] == "dark"
    assert result["compaction"]["reserveTokens"] == 30000
    assert result["compaction"]["keepRecentTokens"] == 10000
    assert result["httpIdleTimeoutMs"] == 7_200_000
    assert result["retry"]["maxRetries"] == 5
    assert result["retry"]["provider"] == {"timeoutMs": 9_000_000, "maxRetries": 0}
    assert result["compaction"]["enabled"] is True
    assert changes == ["compaction.enabled: (없음) -> True"]


def test_values_below_the_floor_are_raised_and_disabled_compaction_is_turned_back_on():
    settings = {"compaction": {"enabled": False, "reserveTokens": 8192, "keepRecentTokens": 60000},
                "httpIdleTimeoutMs": 300000}
    result, changes = pi_settings.apply(settings, 63488)
    assert result["compaction"]["enabled"] is True
    assert result["compaction"]["reserveTokens"] == 23808
    assert result["compaction"]["keepRecentTokens"] == (63488 - 23808) // 3
    assert result["httpIdleTimeoutMs"] == 1_800_000
    assert len(changes) == 5


def test_a_zero_idle_timeout_means_disabled_and_is_left_alone():
    result, _ = pi_settings.apply({"httpIdleTimeoutMs": 0}, 63488)
    assert result["httpIdleTimeoutMs"] == 0


def test_an_unchanged_file_is_not_rewritten(tmp_path):
    path = tmp_path / "settings.json"
    first, _ = pi_settings.apply({}, 63488)
    path.write_text(json.dumps(first, indent=2), encoding="utf-8")
    before = path.stat().st_mtime_ns
    assert pi_settings.main(["--settings", str(path), "--ctx", "63488"]) == 0
    assert path.stat().st_mtime_ns == before


def test_a_missing_file_is_created(tmp_path):
    path = tmp_path / "agent" / "settings.json"
    assert pi_settings.main(["--settings", str(path), "--ctx", "63488"]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["compaction"]["reserveTokens"] == 23808


def test_a_broken_settings_file_fails_loudly_and_is_not_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    assert pi_settings.main(["--settings", str(path), "--ctx", "63488"]) == 1
    assert path.read_text(encoding="utf-8") == "{ not json"


@pytest.mark.parametrize("ctx", ["0", "abc", "62000"])
def test_a_bad_context_is_refused(tmp_path, ctx):
    assert pi_settings.main(["--settings", str(tmp_path / "s.json"), "--ctx", ctx]) == 1


WIN = Path(__file__).resolve().parents[1] / "win"


def _read(name):
    return (WIN / name).read_text(encoding="ascii")


def test_start_pi_applies_the_floors_after_seeding_and_before_waiting_for_the_model():
    body = _read("start-pi.bat")
    call = '%PYTHON_CMD% "%ROOT%tools\\pi_settings.py" --settings "%PI_CODING_AGENT_DIR%\\settings.json" --ctx "%LLAMA_CTX%"'
    assert call in body
    assert body.index("call :sync_packages") < body.index(call) < body.index("tools\\wait_model.py")
    after = body[body.index(call) + len(call):]
    assert after.splitlines()[1].strip() == "if errorlevel 1 exit /b 10"


def test_verify_offline_applies_the_floors_and_counts_a_failure_in_the_render_verdict():
    body = _read("verify-offline.bat")
    assert 'tools\\pi_settings.py" --settings "%PI_CODING_AGENT_DIR%\\settings.json" --ctx "%LLAMA_CTX%"' in body
    assert 'if errorlevel 1 set "RENDER_RC=1"' in body
    assert body.index("call :sync_packages") < body.index("tools\\pi_settings.py") < body.index("pi.exe\" list")


def test_a_small_context_caps_the_default_keep_recent_so_compaction_cannot_loop():
    # Pi 기본 keepRecentTokens 20000은 32768 창의 압축 임계(20480)와 거의 같다 - 압축 직후
    # 다시 임계를 넘는다. 키가 없으면 기본값 20000이 적용된다고 보고 상한으로 누른다.
    result, _ = pi_settings.apply({}, 32768)
    assert result["compaction"]["keepRecentTokens"] == (32768 - 12288) // 3


def test_a_reserve_larger_than_half_the_window_is_capped_and_keep_recent_never_goes_negative():
    # 운영자가 reserveTokens를 창보다 크게 적으면 매 턴 압축이 돌고 keepRecent 상한이 음수가 된다.
    result, changes = pi_settings.apply({"compaction": {"reserveTokens": 70000}}, 63488)
    assert result["compaction"]["reserveTokens"] == 63488 // 2
    assert result["compaction"].get("keepRecentTokens", pi_settings.PI_DEFAULT_KEEP_RECENT) > 0
    assert any("reserveTokens: 70000" in change for change in changes)


@pytest.mark.parametrize("value", [-1, 0, "20000", 3.5, None])
def test_an_invalid_keep_recent_is_replaced_not_passed_through(value):
    # opencode 리뷰: 음수·문자열 keepRecentTokens가 상한 검사를 통과해 Pi로 넘어갔다.
    settings = {"compaction": {"keepRecentTokens": value}} if value is not None else {"compaction": {"keepRecentTokens": None}}
    result, changes = pi_settings.apply(settings, 63488)
    keep = result["compaction"]["keepRecentTokens"]
    assert isinstance(keep, int) and 0 < keep <= pi_settings.floors(63488)["keepRecentTokensMax"]
    assert any("keepRecentTokens" in change for change in changes)


@pytest.mark.parametrize("settings", [{"compaction": 5}, {"retry": "fast"}, {"retry": {"provider": []}}])
def test_non_object_sections_are_replaced_instead_of_crashing(settings):
    result, changes = pi_settings.apply(settings, 63488)
    assert result["compaction"]["reserveTokens"] == 23808
    assert result["retry"]["provider"]["timeoutMs"] == 3_600_000
    assert changes


@pytest.mark.parametrize("ctx", ["8192", "4096", "16128"])
def test_a_context_too_small_for_the_reserve_floor_is_refused(tmp_path, ctx):
    # opencode 리뷰: 8192 창에서 reserve 8192면 압축 임계가 0이다. reserve 하한 8192가
    # 창의 절반 이하가 되는 16384부터 받는다.
    assert pi_settings.main(["--settings", str(tmp_path / "s.json"), "--ctx", ctx]) == 1
    import config_parse
    _, problems = config_parse.parse_text(f'set "LLAMA_CTX={ctx}"\n')
    assert problems


# --- pi-subagents: 단일 슬롯 서버에서 백그라운드 기본 실행을 끈다 -----------------------
# pi-subagents docs/configuration.md: asyncByDefault 가 켜져 있으면 요청이 async 를 생략할 때
# 백그라운드로 돈다. start-llama.bat 은 --parallel 1 이라 부모와 자식이 한 슬롯을 번갈아 쓰고,
# 서로의 KV 를 밀어내 긴 prefill 을 반복하며 대기열에서 타임아웃될 수 있다.


def test_subagent_config_gets_foreground_default_when_absent(tmp_path):
    config = tmp_path / "extensions" / "subagent" / "config.json"
    rc = pi_settings.main(["--settings", str(tmp_path / "settings.json"), "--ctx", "63488", "--subagent-config", str(config)])
    assert rc == 0
    assert json.loads(config.read_text(encoding="utf-8")) == {"asyncByDefault": False}


def test_subagent_config_keeps_an_operator_choice_and_other_keys(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"asyncByDefault": True, "toolDescriptionMode": "full"}), encoding="utf-8")
    before = config.read_text(encoding="utf-8")
    rc = pi_settings.main(["--settings", str(tmp_path / "settings.json"), "--ctx", "63488", "--subagent-config", str(config)])
    assert rc == 0
    assert config.read_text(encoding="utf-8") == before


def test_a_broken_subagent_config_fails_and_is_not_overwritten(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{ nope", encoding="utf-8")
    rc = pi_settings.main(["--settings", str(tmp_path / "settings.json"), "--ctx", "63488", "--subagent-config", str(config)])
    assert rc == 1
    assert config.read_text(encoding="utf-8") == "{ nope"


def test_both_pi_callers_pass_the_subagent_config_path():
    for script in ("start-pi.bat", "verify-offline.bat"):
        body = _read(script)
        line = next(l for l in body.splitlines() if "tools\\pi_settings.py" in l and not l.startswith("rem"))
        assert '--subagent-config "%PI_CODING_AGENT_DIR%\\extensions\\subagent\\config.json"' in line, script
