"""graphify가 만든 HTML의 외부 CDN 스크립트를 번들의 로컬 사본으로 바꾼다.

graphifyy 0.9.65의 HTML 출력은 스크립트를 인터넷에서 받는다:
- exporters/html.py(기본 graph.html): unpkg vis-network 9.1.6 (SRI sha384 포함)
- tree_html.py: d3js.org d3 v7
- callflow_html.py: jsdelivr mermaid 11
폐쇄망에서는 그 요청이 실패해 그래프가 그려지지 않는다(codex R4 #1). 이 도구는 알려진
URL을 같은 폴더의 로컬 파일로 바꾸고, 그 파일을 packages_win/kg/web/에서 복사한다.
사본은 스테이징 PC에서 받아 sha256을 아래에 고정했다(vis-network는 graphify가 적은
SRI sha384와도 일치). 매니페스트가 사본을 해시한다.

모르는 외부 스크립트·스타일시트가 남아 있으면 nonzero로 끝난다 - 조용히 깨진 HTML을
넘기지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "packages_win" / "kg" / "web"

# URL -> (로컬 파일 이름, sha256)
KNOWN = {
    "https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js": (
        "vis-network-9.1.6.min.js",
        "576bb887733eb01bb52ee75b90ef46d818454de5fddb5b616fb8a298d307ca12",
    ),
    "https://d3js.org/d3.v7.min.js": (
        "d3-7.9.0.min.js",
        "f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539",
    ),
    "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js": (
        "mermaid-11.17.2.min.js",
        "581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8",
    ),
}

_TAG = re.compile(r"<script\b[^>]*\bsrc=\"(?P<url>https?://[^\"]+)\"[^>]*>", re.IGNORECASE)
_EXTERNAL = re.compile(r"<(?:script|link)\b[^>]*\b(?:src|href)=\"https?://[^\"]+\"[^>]*>", re.IGNORECASE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite(html: str) -> tuple[str, set[str], list[str]]:
    """(바꾼 HTML, 필요한 로컬 파일 이름들, 남은 외부 참조)."""
    needed: set[str] = set()

    def replace(match: re.Match) -> str:
        url = match.group("url")
        if url not in KNOWN:
            return match.group(0)
        name = KNOWN[url][0]
        needed.add(name)
        # 로컬 파일에는 SRI·CORS 속성이 필요 없고, file:// 페이지에서 crossorigin은
        # 로드를 막을 수 있다. 무결성은 매니페스트와 아래 sha256 대조가 맡는다.
        return f'<script src="{name}">'

    out = _TAG.sub(replace, html)
    leftover = _EXTERNAL.findall(out)
    return out, needed, leftover


_LOCAL_NAMES = {name for name, _ in KNOWN.values()}
_LOCAL_TAG = re.compile(r"<script\b[^>]*\bsrc=\"(?P<name>[^\"/\\:]+)\"", re.IGNORECASE)


def _expected(name: str) -> str:
    return next(sha for n, sha in KNOWN.values() if n == name)


def process(paths: list[Path], web: Path = WEB) -> list[str]:
    """HTML마다: 필요한 로컬 사본을 모두 검증한 뒤에만 복사하고 HTML을 쓴다.

    검증이 하나라도 실패하면 그 HTML은 건드리지 않는다 - 외부 URL이 남아 있어야 다음
    실행이 다시 검사한다(codex R5 #1). 이미 로컬 참조로 바뀐 HTML도 옆의 사본을 다시
    확인하고, 없거나 해시가 다르면 번들 사본으로 되살린다.
    """
    problems: list[str] = []
    files = []
    for path in paths:
        files.extend(sorted(path.glob("*.html")) if path.is_dir() else [path])
    if not files:
        return [f"HTML 파일이 없다: {', '.join(str(p) for p in paths)}"]
    for html_path in files:
        text = html_path.read_text(encoding="utf-8")
        out, needed, leftover = rewrite(text)
        needed |= {m.group("name") for m in _LOCAL_TAG.finditer(out) if m.group("name") in _LOCAL_NAMES}
        local_problems: list[str] = []
        to_copy: list[str] = []
        for name in sorted(needed):
            placed = html_path.parent / name
            if placed.is_file() and _sha256(placed) == _expected(name):
                continue
            source = web / name
            if not source.is_file():
                local_problems.append(f"{source} 없음 - 번들의 packages_win\\kg\\web 이 반입되지 않았다")
            elif _sha256(source) != _expected(name):
                local_problems.append(f"{source} sha256이 고정값과 다르다 - 전송 손상 또는 다른 파일")
            else:
                to_copy.append(name)
        for tag in leftover:
            local_problems.append(f"{html_path.name}: 모르는 외부 참조가 남았다 - {tag[:120]}")
        if local_problems:
            problems.extend(local_problems)
            print(f"[FAIL] {html_path} - 바꾸지 않았다")
            continue
        for name in to_copy:
            shutil.copyfile(web / name, html_path.parent / name)
        if out != text:
            html_path.write_text(out, encoding="utf-8")
        print(f"[ok] {html_path}")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="graphify_offline_html")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("graphify-out")])
    args = parser.parse_args(argv)
    problems = process(args.paths)
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
