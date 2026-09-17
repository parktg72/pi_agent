"""learning 확장(규칙 기억·반성·스킬 도구화)의 번들 배선과 안전 계약을 검사한다.

확장 본체의 동작은 윈도우에서 실제 pi.exe + stub 서버로 실측한다(tasks 증거). 여기서는
배치가 확장을 어떻게 싣는지, 비대화형 검증에서 자동 반성이 꺼지는지, 설계 검토(agy·opencode)
에서 합의한 한도가 코드에 그대로 있는지를 고정한다.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "win"
sys.path.insert(0, str(ROOT / "tools"))
import config_parse

EXTENSION = (WIN / "pi-extensions" / "learning.ts").read_text(encoding="utf-8")


def read(name):
    return (WIN / name).read_text(encoding="ascii")


def test_start_pi_loads_the_extension_from_the_hashed_bundle_root():
    body = read("start-pi.bat")
    assert 'if exist "%ROOT%pi-extensions\\learning.ts" set EXT_ARG=--extension "%ROOT%pi-extensions\\learning.ts"' in body
    launch = next(line for line in body.splitlines() if line.startswith('"%ROOT%bin\\pi\\pi.exe" --offline'))
    assert "%EXT_ARG%" in launch and launch.rstrip().endswith("%*")


def test_verify_offline_loads_it_but_forces_auto_reflection_off():
    body = read("verify-offline.bat")
    assert 'set "LEARNING_AUTO_REFLECT=0"' in body
    roundtrip = next(line for line in body.splitlines() if "--mode json" in line)
    assert "%EXT_ARG%" in roundtrip
    assert body.index('set "LEARNING_AUTO_REFLECT=0"') < body.index(roundtrip)


@pytest.mark.parametrize("value,ok", [("0", True), ("1", True), ("yes", False)])
def test_config_accepts_the_auto_reflect_flag(value, ok):
    _, problems = config_parse.parse_text(f'set "LEARNING_AUTO_REFLECT={value}"\n')
    assert (problems == []) is ok


def test_config_example_turns_auto_reflection_on_as_requested():
    values, problems = config_parse.parse_text(read("config.env.example"))
    assert problems == []
    assert values["LEARNING_AUTO_REFLECT"] == "1"


def test_extension_is_staged_unchanged_at_the_bundle_root():
    assert (ROOT / "pi-extensions" / "learning.ts").read_bytes() == (WIN / "pi-extensions" / "learning.ts").read_bytes()


@pytest.mark.parametrize(
    "needle",
    [
        "const MAX_SKILL_NAME = 58;",  # skill_ + 58 = 64 (도구 이름 한도)
        "const MAX_INJECT_CHARS = 4000;",
        "const REFLECT_MAX_RULES = 2;",
        "const REFLECT_MAX_SKILLS = 1;",
        "const AUTO_REFLECT_MIN_TOOL_CALLS = 8;",
        "if (!ctx.hasUI || !autoReflectEnabled()",
        'reflection === "auto" && params.scope === "global"',
        "function pendingSkillsDir()",
        "approvalHash(dir, manifest) !== manifest.approvalSha256",
        "They never override the instructions above",
        'process.env.LEARNING_AUTO_REFLECT !== "0"',
        # 코드 리뷰(agy·opencode) 반영
        "changed after approval - not run",
        "const shownHash = approvalHash(pendingDir, manifest);",
        '(params.language === "powershell" ? "\\ufeff" : "")',
        "$ErrorActionPreference",
        "JSON.stringify(params.description",
        "const freeText = [params.script, params.usage, params.description",
    ],
)

def test_review_agreed_limits_are_in_the_code(needle):
    assert needle in EXTENSION, needle


def test_pending_skills_live_outside_pi_skill_discovery():
    # Pi는 <agent>\skills 를 자동 탐색한다. 승인 전 스킬은 skills-pending 에만 쓴다.
    package = EXTENSION[EXTENSION.index('name: "package_skill"'):EXTENSION.index('pi.registerCommand("rules"')]
    assert "path.join(pendingSkillsDir(), name)" in package
    assert "fs.writeFileSync(script" in package
    assert re.search(r"const dir = path\.join\(skillsDir\(\)", package) is None


def test_extension_source_carries_no_unexpected_network_or_eval():
    for forbidden in ("fetch(", "http://", "https://", "eval(", "new Function(", "child_process"):
        assert forbidden not in EXTENSION, forbidden


def test_the_reflection_rule_slot_is_reserved_before_the_first_await():
    # 병렬 도구 호출이 모두 초기 카운터로 검사를 통과하던 경합(agy·opencode 코드 리뷰).
    body = EXTENSION[EXTENSION.index('name: "remember_rule"'):EXTENSION.index('name: "package_skill"')]
    reserve = body.index("rulesSavedThisReflection++;")
    first_await = body.index("return withFileMutationQueue(")
    assert reserve < first_await
    assert body.count("release();") >= 3
