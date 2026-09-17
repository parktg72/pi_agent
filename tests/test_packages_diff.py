import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import packages_diff

BUNDLED = ["git:github.com/obra/superpowers@v6.3.0", "npm:pi-subagents@0.68.0"]


def test_identical_lists_say_nothing():
    assert packages_diff.compare(BUNDLED, list(BUNDLED)) == []


def test_a_package_the_new_bundle_added_is_named_as_unregistered():
    lines = packages_diff.compare(BUNDLED, ["git:github.com/obra/superpowers@v6.3.0"])
    assert lines, "v2 번들이 추가한 패키지가 조용히 미등록되면 안 된다"
    assert any("npm:pi-subagents@0.68.0" in line for line in lines)
    assert any("미등록" in line for line in lines)


def test_a_package_only_the_target_has_is_named_too():
    # xcopy /D는 상류에서 삭제된 것을 지우지 않는다. 남아 있는 쪽도 보여야 한다.
    lines = packages_diff.compare(BUNDLED, BUNDLED + ["npm:something-removed@1.0.0"])
    assert any("npm:something-removed@1.0.0" in line for line in lines)


def test_a_version_bump_counts_as_a_difference():
    lines = packages_diff.compare(BUNDLED, ["git:github.com/obra/superpowers@v6.3.0", "npm:pi-subagents@0.49.0"])
    assert any("0.68.0" in line for line in lines)
    assert any("0.49.0" in line for line in lines)


def test_a_settings_json_without_a_package_list_is_not_an_alarm():
    # 최초 실행 직전이거나 사용자가 packages 항목을 지운 경우. 호출자가 파일
    # 존재를 먼저 보므로 여기서 소리를 내면 거짓 경보가 된다.
    assert packages_diff.compare(BUNDLED, None) == []


def test_an_unreadable_bundle_template_says_so():
    lines = packages_diff.compare(None, BUNDLED)
    assert lines and "[warn]" in lines[0]


def test_main_never_blocks_startup(tmp_path, capsys):
    bundled = tmp_path / "settings.packages.json"
    installed = tmp_path / "settings.json"
    bundled.write_text(json.dumps({"packages": BUNDLED}), encoding="utf-8")
    installed.write_text(json.dumps({"packages": [], "trusted": True}), encoding="utf-8")

    exit_code = packages_diff.main(["--bundled", str(bundled), "--installed", str(installed)])
    output = capsys.readouterr().out

    assert exit_code == 0, "대조 결과가 Pi 기동을 막으면 안 된다"
    assert "[warn]" in output
    assert "npm:pi-subagents@0.68.0" in output


def test_main_is_silent_when_the_lists_agree(tmp_path, capsys):
    bundled = tmp_path / "settings.packages.json"
    installed = tmp_path / "settings.json"
    bundled.write_text(json.dumps({"packages": BUNDLED}), encoding="utf-8")
    installed.write_text(json.dumps({"packages": BUNDLED, "trusted": True}), encoding="utf-8")

    assert packages_diff.main(["--bundled", str(bundled), "--installed", str(installed)]) == 0
    assert capsys.readouterr().out == ""


def test_main_survives_a_settings_json_the_user_broke(tmp_path, capsys):
    bundled = tmp_path / "settings.packages.json"
    installed = tmp_path / "settings.json"
    bundled.write_text(json.dumps({"packages": BUNDLED}), encoding="utf-8")
    installed.write_text("{ not json", encoding="utf-8")

    assert packages_diff.main(["--bundled", str(bundled), "--installed", str(installed)]) == 0
