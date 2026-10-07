"""2026-10-02 pi-subagents 도구 스위치(PI_SUBAGENT_TOOLS)의 계약.

근거: tasks/pi-agent-subagents-switch/artifacts/consensus.md(pane 합의)와 번들 pi.exe 0.85.1 +
모의 서버 실측(artifacts/probe/result.md): --exclude-tools는 마지막 것만 적용되고, 세 도구를
빼면 요청이 46.6k자에서 22.9k자가 된다. 토큰·시간은 리허설 11-17에서 잰다.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "win"
sys.path.insert(0, str(ROOT / "tools"))
import config_parse
import subagent_switch

TOOLS = ("subagent", "bg_wait", "subagent_supervisor")
PACKAGE = ROOT / "pi-packages" / "npm" / "node_modules" / "pi-subagents"


def start_pi() -> str:
    return (WIN / "start-pi.bat").read_text(encoding="ascii")


# --- 설정 키 -----------------------------------------------------------------------


def test_the_example_keeps_the_tools_on_until_the_rehearsal_decides():
    values, problems = config_parse.parse_text((WIN / "config.env.example").read_text(encoding="ascii"))
    assert problems == []
    assert values["PI_SUBAGENT_TOOLS"] == "1"


@pytest.mark.parametrize("value,ok", [("1", True), ("0", True), ("", True), ("2", False), ("off", False), ("true", False)])
def test_only_0_and_1_are_accepted(value, ok):
    values, problems = config_parse.parse_text(f'@echo off\nset "PI_SUBAGENT_TOOLS={value}"\n')
    assert (problems == []) is ok
    if ok:
        assert f'set "PI_SUBAGENT_TOOLS={value}"' in config_parse.render_cmd(values)


# --- start-pi.bat ------------------------------------------------------------------


def test_a_blank_or_missing_key_means_on_and_adds_no_argument():
    text = start_pi()
    assert 'if not defined PI_SUBAGENT_TOOLS set "PI_SUBAGENT_TOOLS=1"' in text
    default = text.index('if not defined PI_SUBAGENT_TOOLS set "PI_SUBAGENT_TOOLS=1"')
    empty = text.index('set "SUBAGENT_ARG="')
    branch = text.index('if not "%PI_SUBAGENT_TOOLS%"=="0" goto :subagent_tools_on')
    assert default < empty < branch
    # 켬 쪽 가지는 SUBAGENT_ARG를 건드리지 않는다.
    on_branch = text[text.index("\n:subagent_tools_on\n"):text.index("\n:subagent_tools_done\n")]
    assert "echo [info] pi-subagents tools: on" in on_branch
    assert "SUBAGENT_ARG" not in on_branch


def test_off_excludes_exactly_the_three_tools_and_says_so():
    text = start_pi()
    off = text[text.index('if not "%PI_SUBAGENT_TOOLS%"=="0" goto :subagent_tools_on'):text.index("\n:subagent_tools_on\n")]
    assert f'set "SUBAGENT_ARG=--exclude-tools {",".join(TOOLS)}"' in off
    assert "echo [info] pi-subagents tools: off" in off
    assert "goto :subagent_tools_done" in off


def test_off_checks_the_operator_arguments_before_setting_the_exclusion():
    text = start_pi()
    check = '%PYTHON_CMD% "%ROOT%tools\\subagent_switch.py" %*'
    assert text.count(check) == 1
    refused = text.index("if errorlevel 1 exit /b 12", text.index(check))
    assert text.index(check) < refused < text.index('set "SUBAGENT_ARG=--exclude-tools')
    # 파이썬을 찾은 뒤, 모델을 기다리기 전에 거부한다.
    assert text.index("call :resolve_python") < text.index(check) < text.index("wait_model.py")
    # if ( ) 블록 안이 아니다: %*의 괄호가 블록을 닫지 않게 한다.
    assert not text[:text.index(check)].rstrip().endswith("(")


def test_the_exclusion_comes_before_the_operator_arguments_on_the_pi_command_line():
    launch = [line for line in start_pi().splitlines() if line.startswith('"%ROOT%bin\\pi\\pi.exe" --offline --model')]
    assert len(launch) == 1
    assert launch[0].endswith("%SKILL_ARG% %SUBAGENT_ARG% %*")


def test_nothing_else_about_the_package_is_switched():
    text = start_pi()
    # 패키지 동기화·트리 대조·settings.json 씨앗·asyncByDefault 처리는 스위치와 무관하게 돈다.
    switch = text[text.index("rem pi-subagents tool switch"):text.index("\n:subagent_tools_done\n")]
    for untouched in ("sync_packages", "package_tree.py", "settings.json", "pi_settings.py"):
        assert untouched not in switch
    assert "--subagent-config" in text
    assert "PI_SUBAGENT_TOOLS" not in (WIN / "verify-offline.bat").read_text(encoding="ascii")


# --- 인자 충돌 검사 ------------------------------------------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["-p", "say ok"],
        ["--tools", "read,subagent"],
        ["-t", "read"],
        ["--continue", "--thinking", "high"],
        ["--", "--exclude-tools", "read"],  # -- 뒤는 프롬프트다
        ["-p", "say ok", "--", "--exclude-tools", "read"],
        ["--thinking", "high", "--", "-xt"],
        ["-p", "why does --exclude-tools read not work (here)?"],  # 한 인자 안의 글자
        ["--exclude-toolset", "x"],  # 다른 옵션
    ],
)
def test_arguments_that_do_not_clash(arguments):
    assert subagent_switch.clash(arguments) is None
    assert subagent_switch.main(arguments) == 0


@pytest.mark.parametrize(
    "arguments,found",
    [
        (["--exclude-tools", "read"], "--exclude-tools"),
        (["-xt", "read"], "-xt"),
        (["-p", "hi", "--exclude-tools", "read,bash"], "--exclude-tools"),
        (["--exclude-tools=read"], "--exclude-tools=read"),
        (["-xt=read"], "-xt=read"),
        (["--exclude-tools", "read", "--", "prompt"], "--exclude-tools"),
        (["-p", "--exclude-tools"], "--exclude-tools"),  # 값으로 준 같은 문자열도 거부한다(보수적)
        # `--`가 앞 옵션의 값이면 옵션은 끝나지 않았다: Pi는 뒤의 제외 목록으로 우리 것을 덮는다(codex R3).
        (["--append-system-prompt", "--", "--exclude-tools", "read"], "--exclude-tools"),
        (["--system-prompt", "--", "-xt", "read"], "-xt"),
        # 값 없는 옵션 뒤의 진짜 `--`와 구별하지 못하므로 이것도 거부한다(보수적).
        (["--continue", "--", "--exclude-tools", "read"], "--exclude-tools"),
    ],
)
def test_an_operator_exclusion_before_the_option_end_is_refused(arguments, found, capsys):
    assert subagent_switch.clash(arguments) == found
    assert subagent_switch.main(arguments) == 1
    message = capsys.readouterr().err
    # 자기 목록을 유지하면서 끄는 방법을 한 절차로 알려 준다: 키를 1로 + 세 이름을 목록에.
    assert "PI_SUBAGENT_TOOLS=1" in message and ",".join(TOOLS) in message


# --- 도구 이름이 패키지와 어긋나지 않는다 -----------------------------------------------


@pytest.mark.skipif(not PACKAGE.is_dir(), reason="pi-packages는 gitignore - 스테이징 PC에만 있다")
def test_the_three_names_are_the_tools_the_bundled_package_registers():
    source = PACKAGE / "src"
    registered = {
        "subagent": (source / "extension" / "index.ts", r'name: "subagent",'),
        "bg_wait": (source / "runs" / "background" / "wait-tool.ts", r'name: "bg_wait",'),
        "subagent_supervisor": (
            source / "intercom" / "native-supervisor-channel.ts",
            r'NATIVE_SUPERVISOR_TOOL_NAME = "subagent_supervisor"',
        ),
    }
    assert set(registered) == set(TOOLS)
    for name, (path, pattern) in registered.items():
        assert re.search(pattern, path.read_text(encoding="utf-8")), f"{name}: {path.name}에 등록 이름이 없다"
    # 이 패키지가 메인 세션에 등록하는 도구 이름이 늘면 목록도 같이 봐야 한다.
    names = set()
    for path in source.rglob("*.ts"):
        text = path.read_text(encoding="utf-8")
        if "registerTool" in text:
            names |= set(re.findall(r'^\s*name: "([a-z_]+)",$', text, re.M))
    assert set(TOOLS) - {"subagent_supervisor"} <= names
    assert (PACKAGE / "package.json").read_text(encoding="utf-8").count('"version": "0.68.0"') == 1
