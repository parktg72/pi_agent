"""패키지 트리 대조가 부분 실패를 실제로 잡는지 본다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import package_tree


def make_pair(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "pi-packages" / "npm"
    destination = tmp_path / "home" / "agent" / "npm"
    for root in (source, destination):
        (root / "node_modules" / "pi-subagents").mkdir(parents=True)
        (root / "node_modules" / "pi-subagents" / "package.json").write_text('{"name":"x"}')
        (root / "node_modules" / "pi-subagents" / "index.ts").write_text("export const a = 1;")
    return source, destination


def test_identical_trees_pass(tmp_path):
    source, destination = make_pair(tmp_path)
    failures, warnings = package_tree.compare_trees(source, destination)
    assert failures == [] and warnings == []


def test_a_file_that_never_arrived_is_a_failure(tmp_path):
    # 앵커 파일(package.json)은 남기고 다른 파일만 지운다 - 옛 게이트가
    # 통과시키던 바로 그 부분 실패다.
    source, destination = make_pair(tmp_path)
    (destination / "node_modules" / "pi-subagents" / "index.ts").unlink()
    failures, _ = package_tree.compare_trees(source, destination)
    assert any("놓이지 않음" in failure for failure in failures)
    assert (destination / "node_modules" / "pi-subagents" / "package.json").exists()


def test_a_truncated_file_is_a_failure(tmp_path):
    source, destination = make_pair(tmp_path)
    (destination / "node_modules" / "pi-subagents" / "index.ts").write_text("export")
    failures, _ = package_tree.compare_trees(source, destination)
    assert any("크기 다름" in failure for failure in failures)


def test_a_same_size_different_content_file_is_a_failure(tmp_path):
    # 크기만 비교하면 놓치는 경우. 해시까지 보는 이유가 이것이다.
    source, destination = make_pair(tmp_path)
    (destination / "node_modules" / "pi-subagents" / "index.ts").write_text("export const a = 2;")
    failures, _ = package_tree.compare_trees(source, destination)
    assert any("내용 다름" in failure for failure in failures)


def test_a_file_only_in_the_destination_is_a_failure(tmp_path):
    # 2026-08-20 재리뷰(GPT-5.6 Sol): xcopy /D는 상류에서 삭제된 파일을
    # 지우지 않으므로, 번들 갱신으로 빠진 패키지의 구버전 잔여 파일이 대상에
    # 남아도 이 검사가 조용히 통과시키면 안 된다. "Pi 자신이 여기 쓸 수도
    # 있다"는 가설은 실측(2026-08-20, 실제 pi-packages 트리 + pi.exe list +
    # 오프라인 tool-roundtrip 시도)으로 반증됐다 - npm\\, git\\ 서브트리는
    # 실행 전후 바이트 단위로 동일했다.
    source, destination = make_pair(tmp_path)
    (destination / "node_modules" / "leftover.js").write_text("old")
    failures, warnings = package_tree.compare_trees(source, destination)
    assert any("대상에만 있음" in failure for failure in failures)
    assert warnings == []


def test_a_missing_destination_tree_is_a_failure(tmp_path):
    source, destination = make_pair(tmp_path)
    for path in sorted(destination.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    destination.rmdir()
    failures, _ = package_tree.compare_trees(source, destination)
    assert failures


def test_main_returns_nonzero_when_any_pair_fails(tmp_path):
    source, destination = make_pair(tmp_path)
    assert package_tree.main(["--pair", f"{source}::{destination}"]) == 0
    (destination / "node_modules" / "pi-subagents" / "index.ts").unlink()
    assert package_tree.main(["--pair", f"{source}::{destination}"]) == 1


def test_main_checks_every_pair_not_just_the_first(tmp_path):
    source, destination = make_pair(tmp_path)
    other_source = tmp_path / "pi-packages" / "git"
    other_destination = tmp_path / "home" / "agent" / "git"
    other_source.mkdir(parents=True)
    other_destination.mkdir(parents=True)
    (other_source / "package.json").write_text("{}")
    # 첫 쌍은 멀쩡하고 둘째 쌍이 비어 있다.
    assert package_tree.main(
        ["--pair", f"{source}::{destination}", "--pair", f"{other_source}::{other_destination}"]
    ) == 1


def test_a_malformed_pair_argument_is_refused(tmp_path):
    assert package_tree.main(["--pair", str(tmp_path)]) == 2


def test_main_fails_when_a_stale_leftover_file_sits_in_the_destination(tmp_path):
    # CLI 계약 자체를 고정한다: 대상에만 있는 파일 하나로 main()이 nonzero로
    # 끝나야 한다. compare_trees 단위 테스트와 별개로, 실제로 쓰는 진입점이다.
    source, destination = make_pair(tmp_path)
    assert package_tree.main(["--pair", f"{source}::{destination}"]) == 0
    (destination / "node_modules" / "old-extension.js").write_text("stale")
    assert package_tree.main(["--pair", f"{source}::{destination}"]) == 1
