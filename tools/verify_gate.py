"""verify-offline.bat이 모은 증거를 마지막에 한 번에 판정한다.

설계 원칙 "성공 판정은 종료 코드가 아니라 증거"는 *exit 0을 성공의 증거로
믿지 말라*는 뜻이었지, 실패를 종료 코드로 알리지 말라는 뜻이 아니었다.
2026-08-19 외부 감사(GPT-5.6 Sol)는 매니페스트 누락·pip 실패·import 실패·Pi
연결 오류를 주입해 전부 `EXITCODE=0`을 재현했다. 실패를 nonzero로 내보내는
것은 그 원칙을 **강화**한다 - 증거는 그대로 남고, 운영자는 파일 넷을 눈으로
대조하지 않아도 무엇이 깨졌는지 안다.

그래서 `verify-offline.bat`은 증거를 **끝까지 다 모은 뒤** 이 모듈을 부른다.
중간에 abort하지 않는다 - 증거가 목적이기 때문이다. 판정은 여기서 한 번에
하고, 하나라도 실패하면 nonzero로 끝난다.

2026-08-20 재리뷰(GPT-5.6 Sol)는 이 원칙 자체가 뒤집혀 적용된 자리를 하나
찾았다: Pi 툴 왕복 판정은 JSON 이벤트만 보고 `pi.exe`의 종료 코드
(`--roundtrip-rc`)는 아예 받지도 않았다. "종료 코드만으로 판정하지 않는다"가
"종료 코드를 무시한다"로 잘못 좁혀진 것이다. JSON 조건을 전부 충족시킨 채
`pi.exe`만 nonzero로 죽게 만들면 최종 판정이 통과했다(실측: exit 23으로도
`[PASS] 6개 항목 전부 통과`). 계약은 이제 이렇다 - `성공 = 프로세스 RC 0
AND JSON 내용 전체 통과`. 아직 "정상 완료 후에도 nonzero를 낸다"는 실측이
있는 Pi 버전은 없으므로, 예외 코드는 두지 않는다.

2026-08-21: 다섯 개의 종료 코드 인자(`--manifest-rc`, `--render-rc`,
`--sync-rc`, `--pi-list-rc`, `--roundtrip-rc`)를 모두 필수로 만들었다. 기본값 0은
bat 호출부가 인자를 빠뜨렸을 때 조용히 성공으로 판정하는 버그를 만든다. 호출부
verify-offline.bat이 반드시 다섯 인자를 모두 넘기므로, argparse가 빠진 것을
명확히 실패로 보호해야 한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tool_roundtrip


def package_names(entries: list[str]) -> list[str]:
    """settings.packages.json의 항목에서 `pi list`에 나타날 이름만 뽑는다.

    버전은 뗀다 - 번들과 설치본의 버전이 같은지는 packages_diff.py가 보는
    질문이고, 여기서 보는 것은 "확장이 붙었는가"다.
    """
    names = []
    for entry in entries:
        name = entry
        for prefix in ("npm:", "git:"):
            if name.startswith(prefix):
                name = name[len(prefix) :]
        if "@" in name[1:]:
            name = name[:1] + name[1:].rsplit("@", 1)[0]
        names.append(name)
    return names


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def model_ids(text: str) -> list[str] | None:
    """/v1/models 응답에서 모델 ID를 모은다. 파싱조차 안 되면 None."""
    try:
        document = json.loads(text)
    except ValueError:
        return None
    ids = []
    for node in _walk(document):
        value = node.get("id")
        if isinstance(value, str):
            ids.append(value)
    return ids


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def evaluate(
    evidence: Path,
    alias: str,
    probe_word: str,
    packages: list[str] | None,
    manifest_rc: int,
    render_rc: int,
    sync_rc: int,
    pi_list_rc: int,
    roundtrip_rc: int,
) -> list[tuple[str, bool, str]]:
    """(항목, 통과 여부, 설명) 목록. 순서가 곧 콘솔 요약의 순서다."""
    results: list[tuple[str, bool, str]] = []

    manifest_text = _read(evidence / "manifest-check.txt")
    if manifest_text is None:
        results.append(("번들 무결성", False, "evidence\\manifest-check.txt가 없다"))
    elif manifest_rc != 0:
        results.append(("번들 무결성", False, f"verify_bundle.py 종료 코드 {manifest_rc}"))
    elif "[FAIL]" in manifest_text:
        first = next(line for line in manifest_text.splitlines() if "[FAIL]" in line)
        results.append(("번들 무결성", False, f"매니페스트 불일치: {first.strip()}"))
    else:
        results.append(("번들 무결성", True, "매니페스트와 일치"))

    results.append(
        ("models.json 생성", render_rc == 0, "생성됨" if render_rc == 0 else f"종료 코드 {render_rc}")
    )
    results.append(
        (
            "패키지 트리 동기화",
            sync_rc == 0,
            "반입본과 전량 일치" if sync_rc == 0 else f"종료 코드 {sync_rc}",
        )
    )

    models_text = _read(evidence / "v1-models.json")
    if models_text is None:
        results.append((f"/v1/models의 {alias}", False, "evidence\\v1-models.json이 없다"))
    else:
        ids = model_ids(models_text)
        if ids is None:
            head = models_text.strip().splitlines()[0][:120] if models_text.strip() else "(비어 있음)"
            results.append((f"/v1/models의 {alias}", False, f"JSON이 아니다: {head}"))
        elif alias not in ids:
            results.append((f"/v1/models의 {alias}", False, f"적재된 모델: {', '.join(ids) or '없음'}"))
        else:
            results.append((f"/v1/models의 {alias}", True, "노출됨"))

    list_text = _read(evidence / "pi-packages.txt")
    if not packages:
        # 대조할 목록이 없으면 "4종이 붙었다"를 확인한 것이 아니다. 빈 목록으로
        # 조용히 통과시키면 이 검사는 아무것도 막지 않는다.
        results.append(
            ("확장/스킬 4종", False, "번들의 settings.packages.json에서 패키지 목록을 읽지 못했다")
        )
    elif list_text is None:
        results.append(("확장/스킬 4종", False, "evidence\\pi-packages.txt가 없다"))
    elif pi_list_rc != 0:
        results.append(("확장/스킬 4종", False, f"pi list 종료 코드 {pi_list_rc}"))
    else:
        missing = [name for name in packages if name not in list_text]
        results.append(
            (
                "확장/스킬 4종",
                not missing,
                "모두 나열됨" if not missing else f"목록에 없음: {', '.join(missing)}",
            )
        )

    roundtrip_text = _read(evidence / "pi-tool-roundtrip.json")
    if roundtrip_text is None:
        results.append(("Pi 툴 왕복", False, "evidence\\pi-tool-roundtrip.json이 없다"))
    else:
        problems, facts = tool_roundtrip.judge(roundtrip_text, probe_word)
        # 성공 = 프로세스 RC 0 AND JSON 내용 전체 통과. JSON이 전부 통과해도
        # pi.exe 자신이 nonzero로 죽었다면 그 사실을 감춰서는 안 된다.
        if roundtrip_rc != 0:
            problems = [*problems, f"pi.exe 종료 코드 {roundtrip_rc}"]
        if problems:
            results.append(("Pi 툴 왕복", False, "; ".join(problems)))
        else:
            results.append(
                (
                    "Pi 툴 왕복",
                    True,
                    "stopReason={stop}, 토큰 {tokens}, 도구 호출/결과 있음, 최종 답변에 {probe}, "
                    "pi.exe 종료 코드 0".format(
                        stop=",".join(facts["stop_reasons"]) or "-",
                        tokens=facts["tokens"],
                        probe=probe_word,
                    ),
                )
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_gate", description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--probe-word", required=True)
    parser.add_argument("--packages-file", type=Path, default=None)
    parser.add_argument("--manifest-rc", type=int, required=True)
    parser.add_argument("--render-rc", type=int, required=True)
    parser.add_argument("--sync-rc", type=int, required=True)
    parser.add_argument("--pi-list-rc", type=int, required=True)
    parser.add_argument("--roundtrip-rc", type=int, required=True)
    arguments = parser.parse_args(argv)

    packages: list[str] = []
    if arguments.packages_file and arguments.packages_file.is_file():
        try:
            document = json.loads(arguments.packages_file.read_text(encoding="utf-8"))
            packages = package_names([str(entry) for entry in document.get("packages", [])])
        except ValueError:
            packages = []

    results = evaluate(
        evidence=arguments.evidence,
        alias=arguments.alias,
        probe_word=arguments.probe_word,
        packages=packages,
        manifest_rc=arguments.manifest_rc,
        render_rc=arguments.render_rc,
        sync_rc=arguments.sync_rc,
        pi_list_rc=arguments.pi_list_rc,
        roundtrip_rc=arguments.roundtrip_rc,
    )

    print("")
    print("=== 판정 요약 ===")
    for name, passed, detail in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {name} - {detail}")
    failed = [name for name, passed, _ in results if not passed]
    print("")
    if failed:
        print(f"[FAIL] {len(failed)}/{len(results)} 항목 실패: {', '.join(failed)}", file=sys.stderr)
        print(f"증거는 {arguments.evidence} 에 그대로 남아 있다.", file=sys.stderr)
        return 1
    print(f"[ok] {len(results)}개 항목 전부 통과. 증거는 {arguments.evidence} 에 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
