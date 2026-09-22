"""graphify 스킬을 폐쇄망 Pi용으로 정리한다(스테이징 PC 도구).

원본: 폐쇄망지식그래프/05_skills/graphify/ (graphifyy 0.9.65 동봉 스킬, Apache-2.0).
출력: win/pi-skills/graphify/ - start-pi.bat이 `--skill`로 로드한다.

지우는 것(외부 네트워크를 부르거나 폐쇄망에서 쓸 수 없는 경로):
GitHub clone, `pip`/`uv` 설치·업그레이드, Gemini API, Whisper 전사(모델 다운로드),
URL 수집(`graphify add <url>`), Neo4j/FalkorDB push, 후원 링크.
Step 1의 인터프리터 탐색은 번들 venv(home/kg/venv) 고정으로 바꾼다.

앵커마다 원문에 정확히 한 번 있어야 한다. 상류 문서가 바뀌어 앵커가 사라지면
조용히 원문을 내보내지 않고 실패한다(tests/test_kg_stack.py가 결과를 검사한다).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

OFFLINE_NOTE = """
> **폐쇄망판(pi_agent 번들).** 이 스킬은 외부 네트워크 없이 쓰도록 정리한 사본이다.
> - graphify는 번들의 `home/kg/venv`에 설치돼 있다(`install-kg.bat`). 설치·업그레이드 명령을 실행하지 않는다.
> - 입력은 로컬 경로만 받는다. URL(GitHub 저장소, 웹 문서, 동영상)은 받지 않는다.
> - 코드는 tree-sitter AST로 로컬 파싱하므로 LLM이 필요 없다. 문서·PDF·이미지의 의미 추출은 지금 실행 중인 에이전트(로컬 llama-server)가 한다. API 키를 묻거나 설정하지 않는다.
> - 음성·영상 전사(Whisper)는 모델을 내려받으므로 쓰지 않는다. video/audio 파일은 건너뛴다.
> - Neo4j·FalkorDB로 push하지 않는다. `graphify export neo4j`/`falkordb`의 파일 출력(cypher.txt), `--graphml`, `--svg`, HTML은 로컬이라 쓸 수 있다.
> - graphify의 HTML(graph.html 등)은 그래프 라이브러리를 CDN에서 받는다. HTML을 만든 뒤에는 **반드시** `"$PYTHON" "$PI_AGENT_ROOT/tools/graphify_offline_html.py" graphify-out` 을 실행해 번들의 로컬 사본으로 바꾼다(`$PYTHON`은 Step 1에서 정한 인터프리터).
> - `PI_AGENT_ROOT`(번들 루트)는 `start-pi.bat`이 넣어 준다. graphify는 PATH에서 찾지 않고 이 문서의 모든 명령처럼 번들 venv의 `python.exe -m graphify`로 실행한다 - 다른 graphify가 설치돼 있어도 섞이지 않는다.
"""

STEP0 = """### Step 0 - GitHub repos and multi-path merge (only if a URL or several paths)

폐쇄망판: URL은 받지 않는다. 경로가 URL이면 사용자에게 "폐쇄망에서는 URL을 가져올 수 없다 - 로컬 폴더를 지정하라"고 알리고 멈춘다. 여러 로컬 폴더는 하나씩 처리한다.
"""

STEP1_BLOCK = """```bash
# 폐쇄망판: graphify는 번들의 home/kg/venv에 있다(install-kg.bat). 설치·업그레이드를 시도하지 않는다.
# PI_AGENT_ROOT는 번들 루트(예: /c/pi_agent). 비어 있으면 C:/pi_agent를 가정한다.
PYTHON="${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe"
if ! "$PYTHON" -c "import graphify" 2>/dev/null; then
    echo "graphify가 home/kg/venv에 없다 - 번들 루트에서 install-kg.bat을 먼저 실행하라" >&2
    exit 1
fi
# Write interpreter path for all subsequent steps (persists across invocations)
mkdir -p graphify-out
"$PYTHON" -c "import sys; open('graphify-out/.graphify_python', 'w', encoding='utf-8').write(sys.executable)"
# Save scan root so `graphify update` (no args) knows where to look next time
echo "$(cd INPUT_PATH && pwd)" > graphify-out/.graphify_root
```"""

GUARD_BLOCK = """```bash
# 폐쇄망판: 인터프리터는 번들 venv로만 정한다. 기록이 없거나 다른 인터프리터를 가리키면 다시 쓴다.
BUNDLE_PY="${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe"
BUNDLE_EXE="$("$BUNDLE_PY" -c 'import sys; print(sys.executable)')" || { echo "번들 venv가 없다 - install-kg.bat을 먼저 실행하라" >&2; exit 1; }
if [ ! -f graphify-out/.graphify_python ] || [ "$(cat graphify-out/.graphify_python)" != "$BUNDLE_EXE" ]; then
    mkdir -p graphify-out
    "$BUNDLE_PY" -c "import sys; open('graphify-out/.graphify_python', 'w', encoding='utf-8').write(sys.executable)"
fi
```"""

STEP25 = """### Step 2.5 - Video and audio (only if video files detected)

폐쇄망판: 전사(Whisper)는 모델을 내려받으므로 하지 않는다. `detect`가 video 파일을 찾으면 목록만 사용자에게 알리고 그 파일들은 건너뛴다.
"""

DROP_USAGE_MARKERS = (
    "https://github.com/<owner>",
    "<url1> <url2>",
    "--whisper-model",
    "--neo4j-push",
    "--falkordb-push",
    "/graphify add <url>",
)
DROP_REFERENCES = ("github-and-merge.md", "transcribe.md")


def _replace_once(text: str, old: str, new: str, where: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{where}: 앵커가 {count}번 나온다(1번이어야 함): {old[:60]!r}")
    return text.replace(old, new)


def _cut_between(text: str, start: str, end: str, new: str, where: str) -> str:
    if text.count(start) != 1:
        raise ValueError(f"{where}: 시작 앵커가 {text.count(start)}번 나온다: {start[:60]!r}")
    i = text.index(start)
    j = text.index(end, i)
    return text[:i] + new + text[j:]


def sanitize_skill(text: str) -> str:
    where = "SKILL-agents.md"
    # Usage 블록의 명령 줄(`/graphify ...`)만 지운다. 본문 문단에 같은 플래그 이름이 나오면 아래에서 따로 고친다.
    lines = [
        line
        for line in text.split("\n")
        if not (line.startswith("/graphify") and any(marker in line for marker in DROP_USAGE_MARKERS))
    ]
    text = "\n".join(lines)
    text = _replace_once(
        text,
        "and a plain-language GRAPH_REPORT.md.\n",
        "and a plain-language GRAPH_REPORT.md.\n" + OFFLINE_NOTE,
        where,
    )
    text = _replace_once(
        text,
        "If the path argument starts with `https://github.com/` or `http://github.com/`, treat it as a GitHub URL - run Step 0 before anything else, then continue with the resolved local path.",
        "If the path argument is a URL, stop and tell the user that URLs cannot be fetched in the closed network (Step 0).",
        where,
    )
    text = _cut_between(text, "### Step 0 - GitHub repos", "### Step 1 - Ensure graphify is installed", STEP0 + "\n", where)
    step1 = text.index("### Step 1 - Ensure graphify is installed")
    block_start = text.index("```bash", step1)
    block_end = text.index("```", block_start + len("```bash")) + len("```")
    text = text[:block_start] + STEP1_BLOCK + text[block_end:]
    text = _cut_between(text, "### Step 2.5 - Video and audio", "### Step 3 - Extract entities", STEP25 + "\n", where)
    text = _cut_between(
        text,
        "**Before semantic extraction:** check whether `GEMINI_API_KEY`",
        "> **No other API keys are read.**",
        "",
        where,
    )
    no_keys = text.index("> **No other API keys are read.**")
    no_keys_end = text.index("\n", no_keys)
    text = (
        text[:no_keys]
        + "> **No API keys are read.** Semantic extraction falls to the host agent itself - the running session (local llama-server) is the LLM."
        + text[no_keys_end:]
    )
    text = _replace_once(
        text,
        "uses Gemini **only if** `GEMINI_API_KEY`/`GOOGLE_API_KEY` is already set; otherwise the host agent itself is the LLM.",
        "is done by the host agent itself (the local llama-server); never set `GEMINI_API_KEY`/`GOOGLE_API_KEY` in the closed network - graphify would call an external API.",
        where,
    )
    text = _replace_once(text, "`--neo4j`/`--neo4j-push`, `--falkordb`/`--falkordb-push`", "`--neo4j`, `--falkordb` (file output only)", where)
    text = _replace_once(
        text,
        "### Steps 6b-8 - Wiki, Neo4j, FalkorDB",
        "폐쇄망판: HTML을 만들었으면 여기서 CDN 참조를 로컬 사본으로 바꾼다. 실패(nonzero)하면 사용자에게 그 출력을 보여 준다:\n\n"
        "```bash\n\"$(cat graphify-out/.graphify_python)\" \"$PI_AGENT_ROOT/tools/graphify_offline_html.py\" graphify-out\n```\n\n"
        "### Steps 6b-8 - Wiki, Neo4j, FalkorDB",
        where,
    )
    guard_start = text.index("## Interpreter guard for subcommands")
    block_start = text.index("```bash", guard_start)
    block_end = text.index("```", block_start + len("```bash")) + len("```")
    text = text[:block_start] + GUARD_BLOCK + text[block_end:]
    text = _replace_once(text, "If graphify saved you time, consider supporting it: https://github.com/sponsors/safishamsi\n\n", "", where)
    text = _replace_once(
        text,
        "When the user runs `/graphify add <url>` to fetch a URL into the corpus, or passes `--watch` to auto-rebuild on file changes, see `references/add-watch.md`.",
        "When the user passes `--watch` to auto-rebuild on file changes, see `references/add-watch.md`. URL fetching (`/graphify add`) is not available in the closed network.",
        where,
    )
    return text


BUNDLE_GRAPHIFY = '"${PI_AGENT_ROOT:-/c/pi_agent}/home/kg/venv/Scripts/python.exe" -m graphify'
_BARE_LINE = re.compile(r"^(?P<indent>[ \t]*)graphify (?=\S)", re.MULTILINE)
_BARE_INLINE = re.compile(r"(?<=`)graphify (?=[a-z\"<-])")
_BARE_COMMENT = re.compile(r"(?<=: )graphify (?=[a-z])")


def explicit_graphify(text: str) -> str:
    # 맨몸 `graphify <명령>`은 PATH의 다른 graphify를 부를 수 있다(codex R5 #2). 번들 venv로 고정한다.
    text = _BARE_LINE.sub(lambda m: m.group("indent") + BUNDLE_GRAPHIFY + " ", text)
    text = _BARE_INLINE.sub(BUNDLE_GRAPHIFY + " ", text)
    # 코드 블록 주석의 대안 명령("# or: graphify export html --no-viz")도 복사돼 실행되므로 같이 고친다.
    return _BARE_COMMENT.sub(BUNDLE_GRAPHIFY + " ", text)


_UNQUOTED_PY = re.compile(r'(?<!")\$\(cat graphify-out/\.graphify_python\)(?!")')


def quote_interpreter(text: str) -> str:
    # 설치 경로에 공백이 있으면 인용하지 않은 $(cat ...)는 명령이 둘로 갈라진다(codex R4 #6).
    return _UNQUOTED_PY.sub('"$(cat graphify-out/.graphify_python)"', text)


def sanitize_add_watch(text: str) -> str:
    return _cut_between(
        text,
        "## For /graphify add",
        "## For --watch",
        "## For /graphify add\n\n폐쇄망판: URL 수집은 외부 네트워크가 필요해 쓰지 않는다. 로컬 파일은 입력 폴더에 직접 넣고 `--update`를 돌린다.\n\n---\n\n",
        "add-watch.md",
    ).replace("Load this when the user ran `/graphify add <url>` or passed `--watch`.", "Load this when the user passed `--watch`.")


def sanitize_exports(text: str) -> str:
    text = _replace_once(text, "`--neo4j`, `--neo4j-push`, `--falkordb`, `--falkordb-push`", "`--neo4j`, `--falkordb`", "exports.md")
    text = _cut_between(text, "**If `--neo4j-push <uri>`**", "### Step 7a", "폐쇄망판: Neo4j로 push하지 않는다. 생성한 cypher.txt를 사내 절차로 옮긴다.\n\n", "exports.md")
    text = _cut_between(text, "**If `--falkordb-push <uri>`**", "\n### ", "폐쇄망판: FalkorDB로 push하지 않는다.\n", "exports.md")
    text = _replace_once(text, "(only if --neo4j or --neo4j-push flag)", "(only if --neo4j flag)", "exports.md")
    text = _replace_once(text, "(only if --falkordb or --falkordb-push flag)", "(only if --falkordb flag)", "exports.md")
    text = text.replace(", so prefer `--falkordb-push` to load a graph. Use this only when you want the portable `cypher.txt` artifact", ". The portable `cypher.txt` artifact is the only FalkorDB output here")
    return text


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="sanitize_graphify_skill")
    parser.add_argument("--src", type=Path, required=True, help="폐쇄망지식그래프/05_skills/graphify")
    parser.add_argument("--dst", type=Path, required=True, help="win/pi-skills/graphify")
    parser.add_argument(
        "--license-wheel",
        type=Path,
        default=None,
        help="graphifyy 휠. 주면 그 안의 LICENSE·NOTICE를 사본 옆에 둔다(Apache-2.0 재배포 조건)",
    )
    args = parser.parse_args(argv)
    src, dst = args.src, args.dst
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "references").mkdir(parents=True)
    (dst / "SKILL.md").write_text(explicit_graphify(quote_interpreter(sanitize_skill((src / "SKILL-agents.md").read_text(encoding="utf-8")))), encoding="utf-8", newline="\n")
    for ref in sorted((src / "references").glob("*.md")):
        if ref.name in DROP_REFERENCES:
            continue
        body = ref.read_text(encoding="utf-8")
        if ref.name == "add-watch.md":
            body = sanitize_add_watch(body)
        elif ref.name == "exports.md":
            body = sanitize_exports(body)
        (dst / "references" / ref.name).write_text(explicit_graphify(quote_interpreter(body)), encoding="utf-8", newline="\n")
    if args.license_wheel is not None:
        import zipfile

        with zipfile.ZipFile(args.license_wheel) as wheel:
            for name in wheel.namelist():
                if name.endswith(("/licenses/LICENSE", "/licenses/NOTICE")):
                    (dst / name.rsplit("/", 1)[1]).write_bytes(wheel.read(name))
    print(f"[ok] {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
