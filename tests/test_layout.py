import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import layout


def make_zip(tmp_path: Path, names: list[str]) -> Path:
    archive = tmp_path / "asset.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name in names:
            zf.writestr(name, b"stub")
    return archive


def test_extract_places_every_member(tmp_path):
    archive = make_zip(tmp_path, ["llama-server.exe", "ggml-cuda.dll", "ggml-base.dll"])
    destination = tmp_path / "bin" / "llama-cuda"
    layout.extract(archive, destination)
    assert (destination / "llama-server.exe").is_file()
    assert (destination / "ggml-cuda.dll").is_file()


def test_extract_refuses_paths_that_escape_the_destination(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escaped.txt", b"nope")
    destination = tmp_path / "bin" / "llama-cuda"
    try:
        layout.extract(archive, destination)
    except ValueError as error:
        assert "escaped" in str(error)
    else:
        raise AssertionError("탈출 경로를 허용했다")
    assert not (tmp_path / "bin" / "escaped.txt").exists()


def test_backend_dir_needs_server_and_its_own_backend_dll(tmp_path):
    destination = tmp_path / "bin" / "llama-cuda"
    destination.mkdir(parents=True)
    assert layout.check_backend_dir(destination, "cuda") != []

    (destination / "llama-server.exe").write_bytes(b"x")
    (destination / "ggml-cuda.dll").write_bytes(b"x")
    assert layout.check_backend_dir(destination, "cuda") == []


def test_backend_dirs_may_not_be_mixed(tmp_path):
    destination = tmp_path / "bin" / "llama-cuda"
    destination.mkdir(parents=True)
    (destination / "llama-server.exe").write_bytes(b"x")
    (destination / "ggml-cuda.dll").write_bytes(b"x")
    (destination / "ggml-vulkan.dll").write_bytes(b"x")
    problems = layout.check_backend_dir(destination, "cuda")
    assert any("ggml-vulkan.dll" in p for p in problems)


def test_place_vc_runtime_copies_all_three_dlls(tmp_path):
    source = tmp_path / "vc"
    source.mkdir()
    for name in layout.VC_RUNTIME_DLLS:
        (source / name).write_bytes(b"dll")
    destination = tmp_path / "bin" / "llama-cuda"
    destination.mkdir(parents=True)
    assert layout.place_vc_runtime(source, destination) == []
    for name in layout.VC_RUNTIME_DLLS:
        assert (destination / name).is_file()


def test_place_vc_runtime_reports_what_is_missing(tmp_path):
    source = tmp_path / "vc"
    source.mkdir()
    (source / "VCRUNTIME140.dll").write_bytes(b"dll")
    destination = tmp_path / "bin" / "llama-cuda"
    destination.mkdir(parents=True)
    problems = layout.place_vc_runtime(source, destination)
    assert any("MSVCP140.dll" in p for p in problems)
    assert any("VCRUNTIME140_1.dll" in p for p in problems)


def test_extract_refuses_adjacent_directory_escape(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../llama-cuda-evil/x", b"nope")
    destination = tmp_path / "bin" / "llama-cuda"
    try:
        layout.extract(archive, destination)
    except ValueError as error:
        assert "escaped" in str(error)
    else:
        raise AssertionError("인접 디렉터리 탈출을 허용했다")
    assert not (tmp_path / "bin" / "llama-cuda-evil").exists()


def test_extract_refuses_absolute_paths(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("/etc/passwd", b"nope")
    destination = tmp_path / "bin" / "llama-cuda"
    try:
        layout.extract(archive, destination)
    except ValueError as error:
        assert "escaped" in str(error)
    else:
        raise AssertionError("절대 경로를 허용했다")


def test_every_tool_the_batch_files_run_survives_the_embedded_python():
    # 번들 내장 임베디드 파이썬은 python312._pth 때문에 스크립트 디렉터리를
    # sys.path에 넣지 않는다. 2026-08-19 윈도우 실측에서 render_models_json.py가
    # 바로 그것 때문에 ModuleNotFoundError로 죽었고, 리눅스 유닛 테스트는 그것을
    # 보지 못했다(일반 파이썬은 넣어 준다). 그래서 .bat이 실제로 부르는 도구와
    # 그것들이 끌어오는 형제 모듈만 대상으로, sys.path를 먼저 고치는지 본다.
    # stage.py/assets.py 같은 스테이징 전용 도구는 대상 PC에서 실행되지 않으므로
    # 여기 대상이 아니다.
    import re

    root = Path(__file__).resolve().parents[1]
    tools = root / "tools"
    names = {path.stem for path in tools.glob("*.py")}
    fix = "sys.path.insert(0, str(Path(__file__).resolve().parent))"

    def siblings(stem: str) -> list[str]:
        body = (tools / f"{stem}.py").read_text(encoding="utf-8")
        return [
            match
            for match in re.findall(r"^(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", body, re.M)
            if match in names and match != stem
        ]

    invoked = set()
    for batch in sorted((root / "win").glob("*.bat")):
        invoked |= set(re.findall(r"tools\\([a-z_]+)\.py", batch.read_text(encoding="ascii")))
    assert invoked, "어떤 .bat도 tools를 부르지 않는다고 읽혔다 - 정규식을 의심하라"

    pending, seen = list(invoked), set()
    while pending:
        stem = pending.pop()
        if stem in seen:
            continue
        seen.add(stem)
        imported = siblings(stem)
        pending += imported
        if not imported:
            continue
        body = (tools / f"{stem}.py").read_text(encoding="utf-8")
        assert fix in body, f"{stem}.py가 {imported}를 import하는데 sys.path를 고치지 않는다"
        first_import = min(
            re.search(rf"^(?:import|from)\s+{name}\b", body, re.M).start() for name in imported
        )
        assert body.index(fix) < first_import, stem
