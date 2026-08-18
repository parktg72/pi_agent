import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_imports

REQUIREMENTS = Path(__file__).resolve().parents[1] / "packages_win" / "requirements.txt"


def test_requirement_names_ignores_comments_and_version_ranges():
    text = "\n".join(
        [
            "# 주석 줄",
            "",
            "pandas>=2.1.0,<3.0.0          # lifelines가 <3.0 요구",
            "scikit-learn>=1.8.0,<2.0.0",
            "  # 들여쓴 주석",
            "tqdm",
            "pandas>=2.1.0",
            "--only-binary=:all:",
        ]
    )
    assert check_imports.requirement_names(text) == ["pandas", "scikit-learn", "tqdm"]


def test_distribution_names_are_mapped_to_the_module_that_actually_imports():
    # 기본 규칙(하이픈->밑줄)으로는 못 맞추는 것들. 여기가 틀리면 임포트
    # 검증이 존재하지 않는 모듈을 부르며 전부 FAIL로 물든다.
    for distribution, module in (
        ("scikit-learn", "sklearn"),
        ("scikit-survival", "sksurv"),
        ("python-docx", "docx"),
        ("python-dotenv", "dotenv"),
        ("pyyaml", "yaml"),
    ):
        assert check_imports.module_for(distribution) == (module, True)
    # 표에 없으면 기본 규칙으로 유추하되, 유추했다는 사실을 알린다.
    assert check_imports.module_for("some-new-package") == ("some_new_package", False)


def test_every_requirement_has_a_resolvable_import_name():
    # requirements.txt에 무엇이 추가되든 임포트 이름이 정해진다. 기본 규칙으로
    # 유추한 것은 표에 없으므로, 새 패키지를 추가한 사람이 여기서 알게 된다.
    names = check_imports.requirement_names(REQUIREMENTS.read_text(encoding="utf-8"))
    assert len(names) >= 25, names
    guessed = [name for name in names if not check_imports.module_for(name)[1]]
    for name in guessed:
        assert name.replace("-", "_").islower() or name.islower(), name


def test_a_missing_package_is_reported_as_its_own_failing_line():
    ok, line = check_imports.check("this-package-does-not-exist")
    assert ok is False
    assert line.startswith("FAIL")
    assert "this-package-does-not-exist" in line
    assert "\n" not in line, "실패는 한 줄이어야 증거 파일에서 세어진다"


def test_an_installed_package_is_reported_as_its_own_passing_line():
    ok, line = check_imports.check("pathlib")
    assert ok is True
    assert line.startswith("OK")


def test_main_fails_loudly_when_any_single_package_is_missing(tmp_path, capsys):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pathlib\nthis-package-does-not-exist\n", encoding="utf-8")
    exit_code = check_imports.main(["--requirements", str(requirements)])
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "IMPORT_OK" not in output, "하나라도 실패하면 초록으로 읽히면 안 된다"
    assert "IMPORT_FAILED" in output
    assert "SUMMARY total=2 ok=1 fail=1" in output


def test_main_reports_ok_only_when_everything_imported(tmp_path, capsys):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pathlib\njson\n", encoding="utf-8")
    exit_code = check_imports.main(["--requirements", str(requirements)])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "IMPORT_OK" in output
    assert "SUMMARY total=2 ok=2 fail=0" in output
    assert output.count("\nOK ") + output.startswith("OK ") == 2
