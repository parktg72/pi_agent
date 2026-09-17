"""
Pi 세션 기록에서 사람이 승인한 세션만 골라 LoRA SFT(지도학습)용 JSONL로 추출한다.

전체 세션을 큐레이션 없이 학습하면 모델의 실수나 불필요한 맥락이 그대로 오염으로 이어진다.
그래서 사람이 검토하고 승인한 세션 id 목록(--approved)만 대상으로 한다.

원칙: 학습 샘플 = 추론 때 모델이 실제로 받은 입력 (2026-09-17, 학습은 Colab에서).
손실은 assistant 토큰에만 걸리므로 시스템 프롬프트·도구 스키마의 길이는 품질을 해치지 않는다.

- 시스템 프롬프트·도구 스키마·chat_template_kwargs는 세션 파일에 없다. pi-extensions\\lora-snapshot.ts가
  남긴 "lora-request" custom 엔트리에서 가져온다. 없으면 그 세션은 제외한다.
- 메시지는 Pi 0.85.1이 llama-server로 보내는 규칙 그대로 만든다(bin\\pi\\pi.exe 번들 소스):
  convertToLlm(bashExecution·custom_message·branch_summary -> user), transformMessages(error·aborted
  assistant 제외, 짝 잃은 도구 호출에 합성 결과), openai-completions 직렬화(thinking -> reasoning_content,
  도구 결과 text 파트 줄바꿈 연결).
- 도구 인자는 dict로 쓴다. Qwen3.8 chat_template이 `tool_call.arguments|items`로 읽는다.
- thinking은 기본 보존한다. 템플릿이 과거 assistant의 reasoning까지 모두 렌더하고 Pi도 되돌려 보낸다.
- 샘플 하나 = 같은 요청 스냅샷·같은 compaction 아래의 연속 응답 구간. messages는 구간 마지막 요청 시점의
  전체 문맥(compaction이면 buildContextEntries처럼 요약 + 보존 엔트리 + 이후)이고, 학습 대상은
  train_indices가 가리키는 assistant뿐이다(stopReason이 stop·toolUse인 이 구간의 응답 - 잘린 length 응답은
  문맥으로만 둔다). 세션 중간에 규칙·도구·thinking 수준이 바뀌어도 각 응답을 그 응답을 만든 조건으로
  학습한다(agy·opencode 리뷰).
- 다른 확장이 요청에만 끼워 넣은 user 메시지(스냅샷의 injected)는 기록된 위치에 그대로 넣는다.
- 마지막 완료(stopReason=stop) 응답 뒤의 미완 턴은 잘라낸다. 이미지가 있는 세션(텍스트 LoRA)은 제외한다.
- 비밀처럼 보이는 값은 [REDACTED]로 가린다. 알려진 패턴만 가리므로 반출 전 사람이 보고서와 함께 검토한다.
  사용자 계정 경로·사설 IP·내부 호스트는 모델이 배울 실제 경로라 가리지 않고 보고서에 후보로 나열한다.

출력: --out JSONL(한 줄 = 샘플 하나), 같은 위치의 <이름>.report.md(반출 검토 보고서).
종료코드: 0 내보냄, 2 승인 id 중 세션 폴더에 없는 것이 있음(나머지는 내보냄), 3 내보낼 것이 없음.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import sys

SNAPSHOT_TYPE = "lora-request"
REASONING_FIELDS = ("reasoning", "reasoning_content", "reasoning_text")
TRAINABLE = ("stop", "toolUse")
BRANCH_SUMMARY_PREFIX = "The following is a summary of a branch that this conversation came back from:\n\n<summary>\n"
BRANCH_SUMMARY_SUFFIX = "</summary>"
COMPACTION_SUMMARY_PREFIX = "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"
COMPACTION_SUMMARY_SUFFIX = "\n</summary>"
# 복수형도 가린다(api_keys 등, agy 리뷰). tokens는 max_tokens 같은 평범한 인자와 겹쳐 뺀다.
SECRET_KEY = re.compile(r'(?i)^(?:.*[_-])?(passwords?|passwd|pwd|secrets?|token|api[_-]?keys?|apikeys?|access[_-]?keys?|private[_-]?keys?)$')


SENSITIVE_CANDIDATES = {
    "사용자 계정 경로": re.compile(r'(?i)\b[a-z]:[\\/]+users[\\/]+([^\\/"\s]+)|/home/([^/"\s]+)'),
    "사설 IP": re.compile(r'\b(10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b'),
    "내부 호스트": re.compile(r'(?i)\b([a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:local|lan|corp|internal|intra|intranet|home\.arpa))\b'),
}
GENERIC_ACCOUNTS = {"public", "default", "all users", "default user"}


class Excluded(Exception):
    """세션을 학습 샘플에서 뺄 사유."""


def redact_string(text: str, counter: list[int]) -> str:
    def sub(pattern, replacement, value, flags=0):
        value, n = re.subn(pattern, replacement, value, flags=flags)
        counter[0] += n
        return value

    text = sub(r'-----BEGIN.*?PRIVATE KEY-----.*?-----END.*?PRIVATE KEY-----', '[REDACTED]', text, re.DOTALL)
    text = sub(r'sk-[a-zA-Z0-9-]{20,}', '[REDACTED]', text)
    text = sub(r'AKIA[0-9A-Z]{16}', '[REDACTED]', text)
    text = sub(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}', '[REDACTED]', text)
    text = sub(r'\bgithub_pat_[A-Za-z0-9_]{22,}', '[REDACTED]', text)
    text = sub(r'\bAIza[0-9A-Za-z_-]{35}', '[REDACTED]', text)
    text = sub(r'\bxox[abposr]-[A-Za-z0-9-]{10,}', '[REDACTED]', text)
    text = sub(r'(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{16,}', r'\1[REDACTED]', text)
    text = sub(r'(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+:)[^/\s@]+@', r'\1[REDACTED]@', text)

    # 따옴표 값은 닫는 따옴표까지 가린다 - password="hello world"의 뒤 단어가 남지 않게(opencode 리뷰).
    pattern = (r'(?i)(password|passwd|pwd|secret|token|api_key|apikey)(["\']?\s*[:=]\s*)'
               r'("(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|[^\s\'"\\,}]+)')
    def repl(m):
        counter[0] += 1
        value = m.group(3)
        quote = value[0] if value[:1] in ('"', "'") and len(value) > 1 and value[-1] == value[0] else ''
        return m.group(1) + m.group(2) + quote + '[REDACTED]' + quote
    return re.sub(pattern, repl, text)


def redact_value(value, counter: list[int]):
    """비밀 이름 키의 값: 문자열·숫자는 통째로, 목록은 원소마다 가린다. 객체(도구 스키마 등)는 안으로 들어간다."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (str, int, float)):
        if value == '[REDACTED]' or value == '':
            return value
        counter[0] += 1
        return '[REDACTED]'
    if isinstance(value, list):
        return [redact_value(item, counter) for item in value]
    return redact_recursive(value, counter)


def redact_recursive(data, counter: list[int]):
    if isinstance(data, str):
        return redact_string(data, counter)
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # 인자가 dict라 {"password": "..."}의 키 이름은 문자열 패턴에 걸리지 않는다.
            if SECRET_KEY.match(str(key)) and not isinstance(value, dict):
                result[key] = redact_value(value, counter)
            else:
                result[key] = redact_recursive(value, counter)
        return result
    if isinstance(data, list):
        return [redact_recursive(item, counter) for item in data]
    return data


def text_blocks(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']


def has_image(content) -> bool:
    return isinstance(content, list) and any(isinstance(b, dict) and b.get('type') == 'image' for b in content)


def load_path(file_path):
    """(헤더, 마지막 엔트리부터 루트까지의 경로를 루트->끝 순서로)."""
    entries = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise Excluded(f"JSON 파싱 오류: {e}")
    if not entries or entries[0].get('type') != 'session':
        raise Excluded("세션 헤더 없음")
    header, body = entries[0], entries[1:]
    if not body:
        raise Excluded("빈 세션")
    for entry in body:
        if entry.get('type') == 'message' and not isinstance(entry.get('message'), dict):
            raise Excluded(f"message가 객체가 아님: {type(entry.get('message')).__name__}")
    lookup = {e.get('id'): e for e in body if 'id' in e}
    path, visited = [], set()
    current = body[-1]
    while current is not None:
        if id(current) in visited:
            raise Excluded("parentId 순환")
        visited.add(id(current))
        path.append(current)
        parent = current.get('parentId')
        if parent and parent not in lookup:
            raise Excluded(f"부모 엔트리 없음: {parent}")
        current = lookup[parent] if parent else None
    path.reverse()
    return header, path


def build_context(path, end):
    """buildContextEntries(dist/core/session-manager.js): path[:end+1]에 마지막 compaction을 적용한
    (경로 인덱스, 엔트리) 목록. 요약이 맨 앞, firstKeptEntryId부터의 보존 엔트리, 그 뒤 엔트리 순서다."""
    indexed = list(enumerate(path[:end + 1]))
    compaction = max((i for i, e in indexed if e.get('type') == 'compaction'), default=None)
    if compaction is None:
        return indexed
    first_kept = path[compaction].get('firstKeptEntryId')
    if not first_kept:
        raise Excluded("지원하지 않는 compaction 형식(firstKeptEntryId 없음)")
    kept, found = [], False
    for i, e in indexed[:compaction]:
        found = found or e.get('id') == first_kept
        if found:
            kept.append((i, e))
    return [(compaction, path[compaction])] + kept + indexed[compaction + 1:]


def entry_messages(index, entry):
    """sessionEntryToContextMessages + convertToLlm. 메시지마다 '_src'(경로 인덱스)를 붙인다."""
    kind = entry.get('type')
    if kind == 'message':
        msg = entry['message']
        role = msg.get('role')
        if role in ('user', 'assistant', 'toolResult'):
            return [dict(msg, _src=index)]
        if role == 'custom':
            return [{'role': 'user', 'content': msg.get('content'), '_src': index}]
        if role == 'bashExecution' and not msg.get('excludeFromContext'):
            return [{'role': 'user', 'content': bash_execution_text(msg), '_src': index}]
        return []
    if kind == 'custom_message':
        return [{'role': 'user', 'content': entry.get('content') or [], '_src': index}]
    if kind == 'branch_summary' and entry.get('summary'):
        return [{'role': 'user', 'content': BRANCH_SUMMARY_PREFIX + str(entry['summary']) + BRANCH_SUMMARY_SUFFIX, '_src': index}]
    if kind == 'compaction':
        return [{'role': 'user', 'content': COMPACTION_SUMMARY_PREFIX + str(entry.get('summary', '')) + COMPACTION_SUMMARY_SUFFIX, '_src': index}]
    return []


def bash_execution_text(msg) -> str:
    text = f"Ran `{msg.get('command', '')}`\n"
    output = msg.get('output')
    text += f"```\n{output}\n```" if output else "(no output)"
    exit_code = msg.get('exitCode')
    if msg.get('cancelled'):
        text += "\n\n(command cancelled)"
    elif exit_code is not None and exit_code != 0:
        text += f"\n\nCommand exited with code {exit_code}"
    if msg.get('truncated') and msg.get('fullOutputPath'):
        text += f"\n\n[Output truncated. Full output: {msg['fullOutputPath']}]"
    return text


def tool_calls_of(msg):
    content = msg.get('content')
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get('type') == 'toolCall']


def transform(items):
    """transformMessages: error·aborted assistant 제외, 결과 없는 도구 호출에 합성 결과."""
    result, pending, seen, owner = [], [], set(), -1

    def flush():
        nonlocal pending, seen
        for call in pending:
            if call.get('id') not in seen:
                result.append({'role': 'toolResult', 'toolCallId': call.get('id'), 'isError': True,
                               'content': [{'type': 'text', 'text': 'No result provided'}], '_src': owner})
        pending, seen = [], set()

    for item in items:
        role = item['role']
        if role == 'assistant':
            flush()
            if item.get('stopReason') in ('error', 'aborted'):
                continue
            calls = tool_calls_of(item)
            if calls:
                pending, seen, owner = calls, set(), item['_src']
            result.append(item)
        elif role == 'toolResult':
            seen.add(item.get('toolCallId'))
            result.append(item)
        else:
            flush()
            result.append(item)
    flush()
    return result


def to_chat(msg, keep_thinking, model=None):
    """openai-completions 직렬화와 같은 모양. 보낼 것이 없는 assistant는 None.
    model(요청의 모델 id)과 다른 모델이 만든 응답은 transformMessages처럼 thinking을 평문 text로 바꾼다(agy 리뷰)."""
    role = msg['role']
    if role == 'user':
        return {'role': 'user', 'content': ''.join(text_blocks(msg.get('content')))}
    if role == 'toolResult':
        text = '\n'.join(text_blocks(msg.get('content')))
        return {'role': 'tool', 'tool_call_id': msg.get('toolCallId'), 'content': text or '(no tool output)'}
    content = msg.get('content') if isinstance(msg.get('content'), list) else []
    if model is not None and msg.get('model') != model:
        content = [{'type': 'text', 'text': b.get('thinking', '')} if isinstance(b, dict) and b.get('type') == 'thinking' else b
                   for b in content if not (isinstance(b, dict) and b.get('type') == 'thinking' and b.get('redacted'))]
    text = ''.join(b.get('text', '') for b in content
                   if isinstance(b, dict) and b.get('type') == 'text' and b.get('text', '').strip())
    calls = []
    for b in tool_calls_of(msg):
        if not isinstance(b.get('arguments'), dict):
            # 빈 객체로 바꾸면 틀린 도구 호출을 학습한다(opencode 리뷰).
            raise Excluded(f"도구 인자가 객체가 아님: {b.get('name')}")
        calls.append({'id': b.get('id'), 'type': 'function', 'function': {'name': b.get('name'), 'arguments': b['arguments']}})
    if not text and not calls:
        return None
    result = {'role': 'assistant', 'content': text}
    thinking = [b.get('thinking', '') for b in content
                if isinstance(b, dict) and b.get('type') == 'thinking' and b.get('thinking', '').strip()]
    signed = any(isinstance(b, dict) and b.get('type') == 'thinking' and b.get('thinkingSignature') in REASONING_FIELDS
                 for b in content)
    if keep_thinking and thinking and signed:
        result['reasoning_content'] = '\n'.join(thinking)
    if calls:
        result['tool_calls'] = calls
    return result


def valid_snapshot(data) -> bool:
    injected = data.get('injected', []) if isinstance(data, dict) else None
    return (isinstance(data, dict) and isinstance(data.get('tools'), list)
            and isinstance(data.get('chat_template_kwargs'), dict)
            and (data.get('system') is None or isinstance(data.get('system'), str))
            and (data.get('model') is None or isinstance(data.get('model'), str))
            and isinstance(injected, list)
            and all(isinstance(i, dict) and isinstance(i.get('index'), int) and not isinstance(i.get('index'), bool)
                    and i['index'] >= 0 and isinstance(i.get('content'), str) for i in injected))


def is_response(entry) -> bool:
    msg = entry.get('message') if entry.get('type') == 'message' else None
    return isinstance(msg, dict) and msg.get('role') == 'assistant' and msg.get('stopReason') not in ('error', 'aborted')


def segments_of(path):
    """같은 요청 스냅샷·같은 compaction 아래에서 만들어진 연속 응답을 한 구간으로 묶는다.
    구간 경계가 바뀌면 모델이 본 system·tools·kwargs나 앞 문맥이 달라지기 때문이다."""
    last_stop = max((i for i, e in enumerate(path) if is_response(e) and e['message'].get('stopReason') == 'stop'), default=None)
    if last_stop is None:
        raise Excluded("완료(stopReason=stop)된 응답 없음")
    groups, marker, compaction = [], None, None
    for i, entry in enumerate(path[:last_stop + 1]):
        if entry.get('type') == 'custom' and entry.get('customType') == SNAPSHOT_TYPE:
            marker = i
        elif entry.get('type') == 'compaction':
            compaction = i
        elif is_response(entry) and marker is not None:
            key = (marker, compaction)
            if groups and groups[-1]['key'] == key:
                groups[-1]['end'] = i
            else:
                groups.append({'key': key, 'boundary': max(marker, -1 if compaction is None else compaction), 'end': i})
    if not groups:
        raise Excluded("요청 스냅샷 없음(lora-snapshot 확장 없이 기록된 세션)")
    return groups


def process_session(file_path, keep_thinking):
    """[(샘플, 보고서용 정보)]. 세션 전체를 뺄 사유면 Excluded.

    샘플 하나 = 구간 하나. messages는 그 구간 마지막 요청 시점의 전체 문맥이고, 학습 대상은
    train_indices가 가리키는 assistant 메시지뿐이다(나머지는 문맥으로만 쓴다)."""
    header, path = load_path(file_path)
    groups = segments_of(path)
    results = []
    for number, group in enumerate(groups):
        snapshot = path[group['key'][0]].get('data')
        if not valid_snapshot(snapshot):
            raise Excluded("요청 스냅샷 형식 오류")
        items = transform([m for i, e in build_context(path, group['end']) for m in entry_messages(i, e)])
        for item in items:
            if item['role'] in ('user', 'toolResult') and has_image(item.get('content')):
                raise Excluded("이미지 포함(텍스트 LoRA)")
        messages = [{'role': 'system', 'content': snapshot['system']}] if snapshot.get('system') else []
        targets = []
        for item in items:
            chat = to_chat(item, keep_thinking, snapshot.get('model'))
            if chat is None:
                continue
            if chat['role'] == 'assistant' and item['_src'] > group['boundary'] and item.get('stopReason') in TRAINABLE:
                targets.append(len(messages))
            messages.append(chat)
        for injection in sorted(snapshot.get('injected', []), key=lambda i: i['index']):
            if injection['index'] > len(messages) or (injection['index'] == 0 and messages and messages[0]['role'] == 'system'):
                raise Excluded("주입 메시지 위치가 문맥과 맞지 않음")
            messages.insert(injection['index'], {'role': 'user', 'content': injection['content']})
            targets = [t + 1 if t >= injection['index'] else t for t in targets]
        if not targets or not any(m['role'] == 'user' for m in messages):
            continue
        usage = path[group['end']]['message'].get('usage')
        tokens = usage.get('totalTokens') if isinstance(usage, dict) and isinstance(usage.get('totalTokens'), int) else None
        sample = {
            'session_id': header.get('id'),
            'segment': number,
            'tokens': tokens,
            'train_indices': targets,
            'chat_template_kwargs': snapshot['chat_template_kwargs'],
            'tools': snapshot['tools'],
            'messages': messages,
        }
        info = {
            'cwd': str(header.get('cwd', '')),
            'messages': len(messages),
            'targets': len(targets),
            'injected': len(snapshot.get('injected', [])),
            'tokens': tokens,
            'tools_used': sorted({c['function']['name'] for t in targets
                                  for c in messages[t].get('tool_calls', []) if c['function'].get('name')}),
        }
        results.append((sample, info))
    if not results:
        raise Excluded("학습할 응답 구간 없음")
    return results


def md_cell(value) -> str:
    return str(value).replace('|', '\\|').replace('\n', ' ')


def iter_strings(data):
    if isinstance(data, str):
        yield data
    elif isinstance(data, dict):
        for value in data.values():
            yield from iter_strings(value)
    elif isinstance(data, list):
        for item in data:
            yield from iter_strings(item)


def sensitive_candidates(rows) -> dict[str, list[str]]:
    found = {name: set() for name in SENSITIVE_CANDIDATES}
    for r in rows:
        for text in iter_strings(r['sample']):
            for name, pattern in SENSITIVE_CANDIDATES.items():
                for match in pattern.finditer(text):
                    value = next((g for g in match.groups() if g), match.group(0))
                    if value.lower() not in GENERIC_ACCOUNTS:
                        found[name].add(value)
    return {name: sorted(values) for name, values in found.items()}


def write_report(path, out_path, digest, size, rows, excluded, missing, note=None):
    tokens = [r['info']['tokens'] for r in rows if r['info']['tokens'] is not None]
    unknown = len(rows) - len(tokens)
    lines = [
        "# LoRA 학습 데이터 반출 검토 보고서",
        "",
        f"- 생성(UTC): {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 파일: `{out_path.name}` {size:,} bytes",
        f"- sha256: `{digest}` (무결성 확인용이다. 내용을 보호하지 않는다)",
        f"- 샘플 {len(rows)}개, 학습 대상 응답 {sum(r['info']['targets'] for r in rows)}개",
        f"- 샘플 길이 합계 {sum(tokens):,} 토큰, 최대 {max(tokens, default=0):,} (llama-server usage 기준 근사, 미상 {unknown}개)",
        *([f"- 중단: {note}"] if note else []),
        "",
        "반출 전 확인:",
        "- 샘플에는 시스템 프롬프트(AGENTS.md·학습 규칙 포함), 코드, 파일 경로, 명령 출력, 사고(reasoning) 내용이 그대로 들어 있다.",
        "- 마스킹은 알려진 비밀 패턴만 가린다. 패턴 없는 비밀번호·개인정보·사내 문서 내용은 남는다.",
        "- 외부(Google Colab 등)로 나가도 되는 내용인지 사람이 확인한 뒤 반출한다. AI 도구(Claude Code 등)로 이 파일을 열면 그 서비스로도 전송된다.",
        "",
        "## 샘플",
        "",
        "| session_id | 구간 | cwd | 메시지 | 학습 응답 | 주입 메시지 | tokens | 사용 도구 | 마스킹 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        i = r['info']
        lines.append(f"| {md_cell(r['id'])} | {r['sample']['segment']} | {md_cell(i['cwd'])} | {i['messages']} | {i['targets']} | {i['injected']} "
                     f"| {i['tokens'] if i['tokens'] is not None else '미상'} | {md_cell(', '.join(i['tools_used']) or '-')} | {r['redactions']} |")
    lines += ["", "## 가리지 않은 민감 후보", ""]
    for name, values in sensitive_candidates(rows).items():
        shown = ', '.join(f"`{md_cell(v)}`" for v in values[:50])
        more = f" 외 {len(values) - 50}개" if len(values) > 50 else ""
        lines.append(f"- {name}: {shown}{more}" if values else f"- {name}: 없음")
    lines += ["", "## 제외된 세션", "", "사유는 마스킹을 거친 문구다."]
    lines += [f"- {md_cell(sid)}: {md_cell(reason)}" for sid, reason in excluded] or ["- 없음"]
    lines += ["", "## 세션 폴더에 없는 승인 id", ""]
    lines += [f"- {md_cell(sid)}" for sid in sorted(missing)] or ["- 없음"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(out_path, rows, excluded, missing, note=None):
    # 샘플이 없어도 빈 파일로 덮어 이전 실행의 데이터가 반출되지 않게 한다.
    data = ''.join(json.dumps(r['sample'], ensure_ascii=False) + '\n' for r in rows).encode('utf-8')
    out_path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    report_path = out_path.with_suffix('.report.md')
    write_report(report_path, out_path, digest, len(data), rows, excluded, missing, note)
    print(f"마스킹 치환 건수: {sum(r['redactions'] for r in rows)}", file=sys.stderr)
    print(f"샘플 {len(rows)}개 -> {out_path} (sha256 {digest})")
    print(f"반출 검토 보고서: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="승인된 Pi 세션을 LoRA SFT JSONL로 추출")
    parser.add_argument("--sessions-dir", required=True)
    parser.add_argument("--approved", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--drop-thinking", action="store_true", help="reasoning_content를 빼고 내보낸다")
    # 예전 기본은 thinking 제거였다. 이제 기본이 보존이라 옛 인자는 받기만 한다.
    parser.add_argument("--keep-thinking", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    approved_ids = set()
    try:
        with open(args.approved, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.split('#')[0].strip()
                if line:
                    approved_ids.add(line)
    except Exception as e:
        print(f"Error reading approved list: {e}", file=sys.stderr)
        write_outputs(pathlib.Path(args.out), [], [], set(), note="승인 목록을 읽지 못했다")
        sys.exit(3)

    if not approved_ids:
        # 이전 실행의 train.jsonl이 남아 반출되지 않게 빈 결과로 덮는다(opencode 리뷰).
        write_outputs(pathlib.Path(args.out), [], [], set(), note="승인 목록이 비었다")
        sys.exit(3)

    rows, excluded = [], []
    missing_ids = set(approved_ids)

    sessions_dir = pathlib.Path(args.sessions_dir)
    if sessions_dir.exists():
        for p in sorted(sessions_dir.rglob('*.jsonl')):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    first_line = f.readline().strip()
            except Exception as e:
                print(f"File read error {p}: {e}", file=sys.stderr)
                continue
            if not first_line:
                continue
            try:
                head = json.loads(first_line)
            except json.JSONDecodeError:
                continue
            if head.get('type') != 'session' or head.get('id') not in approved_ids:
                continue
            sid = head['id']
            missing_ids.discard(sid)
            try:
                results = process_session(p, not args.drop_thinking)
            except Exception as e:
                reason = redact_string(str(e) if isinstance(e, Excluded) else f"예외 발생 - {e}", [0])
                excluded.append((sid, reason))
                print(f"제외됨 {sid}: {reason}", file=sys.stderr)
                continue
            for sample, info in results:
                counter = [0]
                sample = redact_recursive(sample, counter)
                # 보고서 필드도 같은 마스킹을 거친다(opencode 리뷰).
                info['cwd'] = redact_string(info['cwd'], [0])
                info['tools_used'] = [redact_string(name, [0]) for name in info['tools_used']]
                rows.append({'id': sid, 'sample': sample, 'info': info, 'redactions': counter[0]})

    rows.sort(key=lambda r: (r['id'], r['sample']['segment']))
    write_outputs(pathlib.Path(args.out), rows, excluded, missing_ids)

    if missing_ids:
        for mid in sorted(missing_ids):
            print(f"누락된 승인 세션: {mid}", file=sys.stderr)
        sys.exit(2)

    if not rows:
        sys.exit(3)

    sys.exit(0)


if __name__ == "__main__":
    main()
