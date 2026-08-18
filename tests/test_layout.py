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
