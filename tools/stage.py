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


def _layout(root: Path, cache: Path, vc_source: Path | None) -> int:
    problems: list[str] = []
    for key, asset in sorted(assets.CATALOG.items()):
        relative, backend = _TARGETS[key]
        destination = root / relative
        layout.extract(cache / asset.name, destination)
        print(f"[ok] {asset.name} -> {relative}")
    for key, (relative, backend) in sorted(_TARGETS.items()):
        if backend:
            problems += layout.check_backend_dir(root / relative, backend)
    if vc_source is not None:
        for relative in sorted({rel for rel, backend in _TARGETS.values() if backend}):
            problems += layout.place_vc_runtime(vc_source, root / relative)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    return 1 if problems else 0


def _manifest(root: Path, target: str) -> int:
    stamped = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = manifest.build(root, staged_at=stamped, target=target)
    (root / "STAGING_MANIFEST.json").write_text(json.dumps(document, indent=2, ensure_ascii=False))
    print(f"[ok] {document['totals']['files']} files, {document['totals']['bytes']} bytes")
    return 0


def _verify(root: Path) -> int:
    document = json.loads((root / "STAGING_MANIFEST.json").read_text())
    problems = manifest.verify(root, document)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    if not problems:
        print("[ok] 매니페스트와 일치한다")
    return 1 if problems else 0


def _model_check(root: Path) -> int:
    models = sorted((root / "models").glob("*.gguf"))
    if not models:
        print("[FAIL] models/ 에 GGUF가 없다", file=sys.stderr)
        return 1
    problems: list[str] = []
    for model in models:
        found = gguf.check_tool_capable(model)
        problems += found
        print(f"[{'FAIL' if found else 'ok'}] {model.name}")
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="stage")
    parser.add_argument("command", choices=["fetch", "layout", "manifest", "verify", "model-check"])
    parser.add_argument("--root", default="/mnt/h/model/pi_agent")
    parser.add_argument("--cache", default="/mnt/h/model/pi_agent/.cache")
    parser.add_argument("--target", default="H:\\model\\pi_agent")
    parser.add_argument("--vc-source", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root)
    cache = Path(args.cache)
    if args.command == "fetch":
        return _fetch(root, cache)
    if args.command == "layout":
        return _layout(root, cache, Path(args.vc_source) if args.vc_source else None)
    if args.command == "manifest":
        return _manifest(root, args.target)
    if args.command == "verify":
        return _verify(root)
    return _model_check(root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
