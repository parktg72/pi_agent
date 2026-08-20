"""마지막 판정이 실패를 실패로 부르는지 본다.

2026-08-19 감사는 매니페스트 누락·pip 실패·import 실패·Pi 연결 오류를 주입해
전부 `EXITCODE=0`을 재현했다. 여기 각 테스트는 그 주입 하나씩에 대응한다.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import verify_gate

PROBE = "NARWHAL-7Q2X"
ALIAS = "qwen3.8-27b"
PACKAGES = [
    "git:github.com/obra/superpowers@v6.3.0",
    "npm:pi-subagents@0.50.0",
    "npm:@juicesharp/rpiv-todo@2.6.1",
    "npm:@juicesharp/rpiv-ask-user-question@2.6.1",
]
ROUNDTRIP = """{"type":"tool_execution_start","toolCall":{"name":"read"}}
{"type":"tool_execution_end","isError":false,"result":"NARWHAL-7Q2X"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"NARWHAL-7Q2X"}]},"stopReason":"stop","usage":{"inputTokens":812,"outputTokens":14}}
"""


@pytest.fixture()
def evidence(tmp_path: Path) -> Path:
    directory = tmp_path / "evidence"
    directory.mkdir()
    (directory / "manifest-check.txt").write_text("[ok] 2789개 파일이 매니페스트와 일치한다", encoding="utf-8")
    (directory / "v1-models.json").write_text(
        json.dumps({"object": "list", "data": [{"id": ALIAS, "object": "model"}]}), encoding="utf-8"
    )
    (directory / "pi-packages.txt").write_text(
        "User packages:\n"
        "  github.com/obra/superpowers 6.3.0\n"
        "  pi-subagents 0.50.0\n"
        "  @juicesharp/rpiv-todo 2.6.1\n"
        "  @juicesharp/rpiv-ask-user-question 2.6.1\n",
        encoding="utf-8",
    )
    (directory / "pi-tool-roundtrip.json").write_text(ROUNDTRIP, encoding="utf-8")
    return directory


def run(evidence: Path, **overrides) -> list[tuple[str, bool, str]]:
    arguments = dict(
        evidence=evidence,
        alias=ALIAS,
        probe_word=PROBE,
        packages=verify_gate.package_names(PACKAGES),
        manifest_rc=0,
        render_rc=0,
        sync_rc=0,
        pi_list_rc=0,
        roundtrip_rc=0,
    )
    arguments.update(overrides)
    return verify_gate.evaluate(**arguments)


def failures(results) -> list[str]:
    return [name for name, passed, _ in results if not passed]


def test_a_clean_run_passes_every_check(evidence):
    assert failures(run(evidence)) == []


def test_a_failed_manifest_check_fails_the_gate(evidence):
    # 감사가 주입한 것: STAGING_MANIFEST.json missing -> EXITCODE=0
    (evidence / "manifest-check.txt").write_text(
        "[FAIL] STAGING_MANIFEST.json 없음", encoding="utf-8"
    )
    assert failures(run(evidence, manifest_rc=1))


def test_a_manifest_failure_with_a_zero_exit_code_still_fails(evidence):
    # 종료 코드만 보면 통과한다 - 내용도 본다.
    (evidence / "manifest-check.txt").write_text("[FAIL] hash mismatch: bin/pi/pi.exe", encoding="utf-8")
    assert failures(run(evidence))


def test_a_missing_manifest_evidence_file_fails(evidence):
    (evidence / "manifest-check.txt").unlink()
    assert failures(run(evidence))


def test_a_models_json_render_failure_fails_the_gate(evidence):
    assert "models.json 생성" in failures(run(evidence, render_rc=1))


def test_a_package_tree_mismatch_fails_the_gate(evidence):
    assert "패키지 트리 동기화" in failures(run(evidence, sync_rc=1))


def test_the_alias_missing_from_v1_models_fails(evidence):
    (evidence / "v1-models.json").write_text(
        json.dumps({"data": [{"id": "some-other-model"}]}), encoding="utf-8"
    )
    assert failures(run(evidence))


def test_a_powershell_error_instead_of_json_fails(evidence):
    # 서버가 안 떠 있으면 Invoke-RestMethod의 오류 텍스트가 그 자리에 남는다.
    (evidence / "v1-models.json").write_text(
        "Invoke-RestMethod : Unable to connect to the remote server", encoding="utf-8"
    )
    assert failures(run(evidence))


def test_a_missing_extension_fails(evidence):
    text = (evidence / "pi-packages.txt").read_text(encoding="utf-8")
    (evidence / "pi-packages.txt").write_text(
        text.replace("  @juicesharp/rpiv-todo 2.6.1\n", ""), encoding="utf-8"
    )
    assert failures(run(evidence))


def test_a_nonzero_pi_list_fails(evidence):
    assert failures(run(evidence, pi_list_rc=1))


def test_a_connection_error_in_the_round_trip_fails(evidence):
    # 감사가 재현한 것: stopReason error인데 EXITCODE=0.
    (evidence / "pi-tool-roundtrip.json").write_text(
        '{"type":"assistant","message":{"role":"assistant","content":""},'
        '"stopReason":"error","error":"Connection error.","usage":{"inputTokens":0}}',
        encoding="utf-8",
    )
    assert "Pi 툴 왕복" in failures(run(evidence))


def test_a_missing_round_trip_file_fails(evidence):
    (evidence / "pi-tool-roundtrip.json").unlink()
    assert "Pi 툴 왕복" in failures(run(evidence))


def test_a_nonzero_pi_exit_code_fails_even_with_perfect_json(evidence):
    # 2026-08-20 재리뷰(GPT-5.6 Sol) 실측: JSON 조건을 전부 충족시킨 채
    # pi.exe만 exit 23으로 죽여도 예전 게이트는 [PASS] 6개 전부 통과였다.
    # evidence 픽스처의 ROUNDTRIP JSON은 완전히 정상이다 - roundtrip_rc만
    # 바꿔서 그것만으로 실패해야 한다.
    assert "Pi 툴 왕복" in failures(run(evidence, roundtrip_rc=23))


def test_a_zero_pi_exit_code_with_perfect_json_still_passes(evidence):
    # 대조군: 프로세스 RC 0이고 JSON도 통과하면 이 항목은 여전히 통과한다.
    assert "Pi 툴 왕복" not in failures(run(evidence, roundtrip_rc=0))


def test_main_wires_roundtrip_rc_from_argv(evidence, tmp_path):
    packages_file = tmp_path / "settings.packages.json"
    packages_file.write_text(json.dumps({"packages": PACKAGES}), encoding="utf-8")
    argv = [
        "--evidence", str(evidence),
        "--alias", ALIAS,
        "--probe-word", PROBE,
        "--packages-file", str(packages_file),
        "--roundtrip-rc", "23",
    ]
    assert verify_gate.main(argv) == 1


def test_package_names_drops_the_source_prefix_and_the_version():
    assert verify_gate.package_names(PACKAGES) == [
        "github.com/obra/superpowers",
        "pi-subagents",
        "@juicesharp/rpiv-todo",
        "@juicesharp/rpiv-ask-user-question",
    ]


def test_main_returns_nonzero_and_names_the_failing_checks(evidence, capsys, tmp_path):
    packages_file = tmp_path / "settings.packages.json"
    packages_file.write_text(json.dumps({"packages": PACKAGES}), encoding="utf-8")
    argv = [
        "--evidence", str(evidence),
        "--alias", ALIAS,
        "--probe-word", PROBE,
        "--packages-file", str(packages_file),
    ]
    assert verify_gate.main(argv) == 0
    assert "PASS" in capsys.readouterr().out

    (evidence / "manifest-check.txt").write_text("[FAIL] hash mismatch: models/x.gguf", encoding="utf-8")
    assert verify_gate.main(argv) == 1
    captured = capsys.readouterr()
    assert "[FAIL] 번들 무결성" in captured.out
    assert "번들 무결성" in captured.err


def test_an_unreadable_package_list_is_a_failure_not_a_free_pass(evidence):
    # 대조할 목록이 없으면 "확장 4종이 붙었다"를 확인한 것이 아니다.
    assert "확장/스킬 4종" in failures(run(evidence, packages=[]))
    assert "확장/스킬 4종" in failures(run(evidence, packages=None))


def test_a_run_without_the_bundled_package_list_does_not_pass(evidence, capsys):
    assert verify_gate.main(
        ["--evidence", str(evidence), "--alias", ALIAS, "--probe-word", PROBE]
    ) == 1


def test_the_summary_lists_every_check_by_name(evidence, capsys, tmp_path):
    # 운영자가 파일 넷을 눈으로 대조하지 않아도 알 수 있어야 한다.
    packages_file = tmp_path / "settings.packages.json"
    packages_file.write_text(json.dumps({"packages": PACKAGES}), encoding="utf-8")
    verify_gate.main(
        [
            "--evidence", str(evidence),
            "--alias", ALIAS,
            "--probe-word", PROBE,
            "--packages-file", str(packages_file),
        ]
    )
    out = capsys.readouterr().out
    for name in ("번들 무결성", "models.json 생성", "패키지 트리 동기화", ALIAS, "확장/스킬 4종", "Pi 툴 왕복"):
        assert name in out
