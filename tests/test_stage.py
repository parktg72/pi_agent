import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import stage


def test_plan_targets_maps_every_catalog_entry_to_its_own_directory():
    import assets

    targets = stage.plan_targets()
    assert set(targets) == set(assets.CATALOG), "카탈로그에 있는데 배치 대상이 없는 자산은 조용히 누락된다"
    assert targets["pi"] == ("bin/pi", "")
    assert targets["llama-cuda"] == ("bin/llama-cuda", "cuda")
    assert targets["llama-cudart"] == ("bin/llama-cuda", "")
    assert targets["llama-vulkan"] == ("bin/llama-vulkan", "vulkan")
    assert targets["llama-cpu"] == ("bin/llama-cpu", "cpu")
    assert targets["python-embed"] == ("bin/python", "")


def test_manifest_command_writes_a_document_and_verifies_it(tmp_path, capsys):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pi.exe").write_bytes(b"x")
    code = stage.main(["manifest", "--root", str(tmp_path), "--target", "H:\\model\\pi_agent"])
    assert code == 0
    document = json.loads((tmp_path / "STAGING_MANIFEST.json").read_text())
    assert document["totals"]["files"] == 1

    code = stage.main(["verify", "--root", str(tmp_path)])
    assert code == 0


def test_verify_command_fails_after_tampering(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pi.exe").write_bytes(b"x")
    stage.main(["manifest", "--root", str(tmp_path), "--target", "T"])
    (tmp_path / "bin" / "pi.exe").write_bytes(b"tampered")
    assert stage.main(["verify", "--root", str(tmp_path)]) == 1


def test_fetch_refuses_a_catalog_entry_without_a_pinned_hash(monkeypatch, tmp_path):
    import assets

    unpinned = assets.Asset(name="x.zip", url="https://example/x.zip", sha256=None, bytes=None)
    monkeypatch.setitem(assets.CATALOG, "llama-vulkan", unpinned)
    code = stage.main(["fetch", "--root", str(tmp_path), "--cache", str(tmp_path / ".cache")])
    assert code == 1


def test_layout_refuses_to_extract_when_cache_file_is_tampered(tmp_path, capsys):
    # 자산 하나만 캐시에 두면 sorted(CATALOG)가 그보다 앞선 키에서 "missing file:"로
    # 먼저 1을 반환해 변조 분기에 닿지 않는다. 전부 정상으로 놓고 하나만 변조한다.
    import hashlib
    import unittest.mock as mock
    import zipfile

    import assets

    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()

    pinned = {}
    for key, asset in assets.CATALOG.items():
        path = cache_dir / asset.name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("llama-server.exe", key)
        payload = path.read_bytes()
        pinned[key] = assets.Asset(
            name=asset.name,
            url=asset.url,
            sha256=hashlib.sha256(payload).hexdigest(),
            bytes=len(payload),
        )

    victim = "llama-vulkan"
    tampered_name = pinned[victim].name
    (cache_dir / tampered_name).write_bytes(b"TAMPERED" * 4)

    with mock.patch("assets.CATALOG", pinned):
        code = stage.main(
            ["layout", "--root", str(tmp_path), "--cache", str(cache_dir), "--skip-vc-runtime"]
        )
    assert code == 1
    stderr = capsys.readouterr().err
    assert "missing file" not in stderr, f"변조 분기에 닿지 못했다: {stderr}"
    assert tampered_name in stderr, stderr
    assert "sha256 mismatch" in stderr or "bytes mismatch" in stderr, stderr
    assert not (tmp_path / "bin").exists(), "검증 실패 후에도 압축을 풀었다"


def test_layout_requires_vc_source_or_skip_flag(tmp_path, capsys):
    import zipfile
    import assets
    import unittest.mock as mock

    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir()

    # Create minimal zip files for each asset
    for key, asset in {
        "pi": "pi-windows-x64.zip",
        "llama-cuda": f"llama-b10470-bin-win-cuda-12.4-x64.zip",
        "llama-cudart": "cudart-llama-bin-win-cuda-12.4-x64.zip",
        "llama-vulkan": f"llama-b10470-bin-win-vulkan-x64.zip",
        "llama-cpu": f"llama-b10470-bin-win-cpu-x64.zip",
    }.items():
        z = zipfile.ZipFile(cache_dir / asset, "w")
        z.close()

    # Mock assets with pinned hashes/bytes to pass verification
    pinned_catalog = {
        k: assets.Asset(
            name=v,
            url="http://example.com/" + v,
            sha256="0000000000000000000000000000000000000000000000000000000000000000",
            bytes=22,  # minimum zip file size
        )
        for k, v in {
            "pi": "pi-windows-x64.zip",
            "llama-cuda": f"llama-b10470-bin-win-cuda-12.4-x64.zip",
            "llama-cudart": "cudart-llama-bin-win-cuda-12.4-x64.zip",
            "llama-vulkan": f"llama-b10470-bin-win-vulkan-x64.zip",
            "llama-cpu": f"llama-b10470-bin-win-cpu-x64.zip",
        }.items()
    }

    with mock.patch("assets.CATALOG", pinned_catalog):
        with mock.patch("assets.verify_downloaded", return_value=[]):
            with mock.patch("layout.extract"):
                with mock.patch("layout.check_backend_dir", return_value=[]):
                    # Subtest 1: Without --vc-source and without --skip-vc-runtime, should fail
                    # and the failure reason should mention vc-source or skip-vc-runtime
                    code = stage.main(["layout", "--root", str(tmp_path), "--cache", str(cache_dir)])
                    assert code == 1
                    captured = capsys.readouterr()
                    stderr_text = captured.err
                    assert "--vc-source" in stderr_text or "--skip-vc-runtime" in stderr_text, \
                        f"vc-source gate message not found in stderr: {stderr_text}"

                    # Subtest 2: With --skip-vc-runtime, should succeed
                    code = stage.main(["layout", "--root", str(tmp_path), "--cache", str(cache_dir), "--skip-vc-runtime"])
                    assert code == 0


def test_manifest_and_verify_require_root_argument(tmp_path):
    import pytest

    # Commands should require --root to be specified
    with pytest.raises(SystemExit):
        stage.main(["manifest", "--target", "H:\\model\\pi_agent"])


def test_manifest_and_verify_pin_utf8_explicitly(tmp_path):
    # 매니페스트는 ensure_ascii=False로 쓰이고 비ASCII 경로(README-폐쇄망.md)를 담는다.
    # 윈도우 기본 코드페이지(CP949)에서 encoding 없이 읽으면 UnicodeDecodeError다.
    (tmp_path / "README-폐쇄망.md").write_text("# 폐쇄망 반입 안내\n", encoding="utf-8")
    assert stage.main(["manifest", "--root", str(tmp_path), "--target", "T"]) == 0

    raw = (tmp_path / "STAGING_MANIFEST.json").read_bytes()
    assert "README-폐쇄망.md".encode("utf-8") in raw, "매니페스트가 UTF-8로 쓰이지 않았다"
    assert stage.main(["verify", "--root", str(tmp_path)]) == 0

    # 이 프로세스의 기본 인코딩이 이미 UTF-8이라 위 왕복만으로는 로케일 의존을
    # 배제하지 못한다. 그래서 파일 입출력이 encoding을 명시했는지를 소스로 직접 본다.
    import re

    source = Path(stage.__file__).read_text(encoding="utf-8")
    calls = re.findall(r"\.(?:read_text|write_text)\((?:[^()]|\([^()]*\))*\)", source, flags=re.S)
    assert calls, "stage.py에서 텍스트 입출력을 찾지 못했다 - 테스트가 낡았다"
    for call in calls:
        assert 'encoding="utf-8"' in call, call
