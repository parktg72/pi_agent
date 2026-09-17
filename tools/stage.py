"""스테이징 CLI — fetch, layout, manifest, verify, model-check.

해시가 고정되지 않은 자산은 받지 않는다. 핀 없는 다운로드는 다음 릴리스가
조용히 다른 것을 주어도 알 수 없다.
"""
from __future__ import annotations

import argparse
import datetime as _datetime
import json
import sys
from pathlib import Path

import assets
import gguf
import layout
import manifest

_TARGETS: dict[str, tuple[str, str]] = {
    "pi": ("bin/pi", ""),
    "llama-cuda": ("bin/llama-cuda", "cuda"),
    "llama-cudart": ("bin/llama-cuda", ""),
    "llama-vulkan": ("bin/llama-vulkan", "vulkan"),
    "llama-cpu": ("bin/llama-cpu", "cpu"),
    "python-embed": ("bin/python", ""),
}


def plan_targets() -> dict[str, tuple[str, str]]:
    return dict(_TARGETS)


def _fetch(root: Path, cache: Path) -> int:
    unpinned = [key for key, asset in assets.CATALOG.items() if not asset.sha256 or not asset.bytes]
    if unpinned:
        print(f"[FAIL] 해시가 고정되지 않은 자산: {', '.join(sorted(unpinned))}", file=sys.stderr)
        return 1
    for key, asset in sorted(assets.CATALOG.items()):
        path = assets.download(asset, cache)
        problems = assets.verify_downloaded(path, asset)
        if problems:
            for problem in problems:
                print(f"[FAIL] {problem}", file=sys.stderr)
            return 1
        print(f"[ok] {key} {asset.name}")
    return 0


def _layout(root: Path, cache: Path, vc_source: Path | None, skip_vc_runtime: bool) -> int:
    problems: list[str] = []

    # Verify cache files before extracting
    for key, asset in sorted(assets.CATALOG.items()):
        cache_file = cache / asset.name
        verify_problems = assets.verify_downloaded(cache_file, asset)
        if verify_problems:
            for problem in verify_problems:
                print(f"[FAIL] {problem}", file=sys.stderr)
            return 1

    # Extract verified files
    for key, asset in sorted(assets.CATALOG.items()):
        relative, backend = _TARGETS[key]
        destination = root / relative
        layout.extract(cache / asset.name, destination)
        print(f"[ok] {asset.name} -> {relative}")

    # Check backend directories
    for key, (relative, backend) in sorted(_TARGETS.items()):
        if backend:
            problems += layout.check_backend_dir(root / relative, backend)

    # Handle VC++ runtime
    if not skip_vc_runtime:
        if vc_source is None:
            print("[FAIL] --vc-source를 제공하거나 --skip-vc-runtime을 명시하라", file=sys.stderr)
            return 1
        for relative in sorted({rel for rel, backend in _TARGETS.values() if backend}):
            problems += layout.place_vc_runtime(vc_source, root / relative)
    else:
        print("[warn] VC++ 런타임을 배치하지 않았다 - 대상 PC에 이미 설치되어 있어야 한다")

    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    return 1 if problems else 0


def _manifest(root: Path, target: str) -> int:
    stamped = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = manifest.build(root, staged_at=stamped, target=target)
    # 매니페스트는 ensure_ascii=False로 쓰이고 비ASCII 경로(README-폐쇄망.md)를 담는다.
    # 윈도우 기본 코드페이지(CP949)로 읽고 쓰면 UnicodeDecodeError다 — 양쪽 모두 UTF-8로 못 박는다.
    (root / "STAGING_MANIFEST.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[ok] {document['totals']['files']} files, {document['totals']['bytes']} bytes")
    return 0


def _verify(root: Path) -> int:
    document = json.loads((root / "STAGING_MANIFEST.json").read_text(encoding="utf-8"))
    problems = manifest.verify(root, document)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if not problems:
        print("[ok] 매니페스트와 일치한다")
    return 1 if problems else 0


def _model_check(root: Path) -> int:
    # 반입하지 않는 모델(manifest.EXCLUDED_PATHS)은 검사하지 않는다 - 번들에 없는 것이다.
    models = sorted(
        path for path in (root / "models").glob("*.gguf")
        if path.relative_to(root).as_posix() not in manifest.EXCLUDED_PATHS
    )
    if not models:
        print("[FAIL] models/ 에 GGUF가 없다", file=sys.stderr)
        return 1
    problems: list[str] = []
    checked = 0
    for model in models:
        # 비전 프로젝터(mmproj, general.architecture=clip)는 채팅 모델이 아니라
        # 템플릿이 원래 없다. 2026-09-17 이것이 FAIL로 찍혀 오탐이었다. 면제는
        # mmproj 이름에만 준다 - 채팅 모델 이름으로 놓인 프로젝터는 그대로 검사해
        # 실패시킨다(opencode 리뷰).
        architecture = gguf.read_metadata(model, ("general.architecture",)).get("general.architecture")
        if architecture == "clip" and model.name.lower().startswith("mmproj"):
            print(f"[skip] {model.name} - 비전 프로젝터(clip), 채팅 템플릿 검사 대상 아님")
            continue
        checked += 1
        found = gguf.check_tool_capable(model)
        problems += found
        print(f"[{'FAIL' if found else 'ok'}] {model.name}")
    if checked == 0:
        problems.append("검사한 채팅 모델이 하나도 없다 - models/에 프로젝터만 남았다")
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="stage")
    parser.add_argument("command", choices=["fetch", "layout", "manifest", "verify", "model-check"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--cache", default=None)
    parser.add_argument("--target", default="H:\\model\\pi_agent")
    parser.add_argument("--vc-source", default=None)
    parser.add_argument("--skip-vc-runtime", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.command == "fetch":
        if args.cache is None:
            print("[FAIL] fetch는 --cache를 요구한다", file=sys.stderr)
            return 1
        cache = Path(args.cache)
        return _fetch(root, cache)

    if args.command == "layout":
        if args.cache is None:
            print("[FAIL] layout은 --cache를 요구한다", file=sys.stderr)
            return 1
        cache = Path(args.cache)
        return _layout(root, cache, Path(args.vc_source) if args.vc_source else None, args.skip_vc_runtime)

    if args.command == "manifest":
        return _manifest(root, args.target)

    if args.command == "verify":
        return _verify(root)

    return _model_check(root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
