"""
Pi 세션 기록에서 승인된 세션만 선별하여 SFT (지도학습)용 JSONL 형식으로 추출하는 도구입니다.
전체 세션을 큐레이션 없이 바로 학습(자기증류)하면 모델의 실수나 불필요한 맥락이 그대로 오염으로 이어져 파국적 망각과 성능 저하를 부릅니다.
이 도구는 사람이 검토하고 승인한 세션 id 목록(--approved)만을 대상으로 활성 경로(마지막 노드부터 루트까지)를 추출하며, 내부 기밀 정보(비밀번호, 토큰, 프라이빗 키)를 [REDACTED]로 마스킹합니다.
"""
import sys
import json
import argparse
import pathlib
import re

def redact_string(text: str, counter: list[int]) -> str:
    # 1. Private key
    text, n = re.subn(r'-----BEGIN.*?PRIVATE KEY-----.*?-----END.*?PRIVATE KEY-----', '[REDACTED]', text, flags=re.DOTALL)
    counter[0] += n
    
    # 2. SK token
    text, n = re.subn(r'sk-[a-zA-Z0-9-]{20,}', '[REDACTED]', text)
    counter[0] += n
    
    # 3. AWS AKIA
    text, n = re.subn(r'AKIA[0-9A-Z]{16}', '[REDACTED]', text)
    counter[0] += n
    
    # 4. password, secret, etc.
    pattern = r'(?i)(password|passwd|pwd|secret|token|api_key|apikey)(["\']?\s*[:=]\s*["\']?)([^\s\'"\\,}]+)'
    def repl(m):
        counter[0] += 1
        return m.group(1) + m.group(2) + '[REDACTED]'
    text = re.sub(pattern, repl, text)
    return text

def redact_recursive(data, counter: list[int]):
    if isinstance(data, str):
        return redact_string(data, counter)
    elif isinstance(data, dict):
        return {k: redact_recursive(v, counter) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_recursive(item, counter) for item in data]
    return data

def extract_contents(contents, keep_thinking):
    if isinstance(contents, str):
        return {"content": contents}
        
    if not isinstance(contents, list):
        return {"content": ""}

    text_parts = []
    reasoning_parts = []
    tool_calls = []
    
    for block in contents:
        t = block.get('type')
        if t == 'text':
            text_parts.append(block.get('text', ''))
        elif t == 'thinking':
            if keep_thinking:
                reasoning_parts.append(block.get('thinking', ''))
        elif t == 'image':
            text_parts.append('[image omitted]')
        elif t == 'toolCall':
            args = block.get('arguments', {})
            tool_calls.append({
                "id": block.get('id'),
                "type": "function",
                "function": {
                    "name": block.get('name'),
                    "arguments": json.dumps(args, ensure_ascii=False)
                }
            })
            
    content_val = "".join(text_parts)
    if not text_parts and tool_calls:
        content_val = None
        
    res = {"content": content_val}
    if reasoning_parts:
        res["reasoning_content"] = "".join(reasoning_parts)
    if tool_calls:
        res["tool_calls"] = tool_calls
    return res

def process_session(file_path, keep_thinking):
    entries = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                return None, f"Parse error on line: {e}"
                
    if not entries:
        return None, "empty file"
        
    last_entry = entries[-1]
    
    lookup = {e.get('id'): e for e in entries if 'id' in e}
    path = []
    curr = last_entry
    while curr:
        path.append(curr)
        pid = curr.get('parentId')
        if pid and pid in lookup:
            curr = lookup[pid]
        else:
            break
            
    path.reverse()
    
    messages = []
    last_assistant = None
    
    for entry in path:
        if entry.get('type') != 'message':
            continue
        msg = entry.get('message', {})
        
        # In case msg is not dict (e.g. malformed)
        if not isinstance(msg, dict):
            raise ValueError(f"message is not a dictionary: {type(msg)}")
            
        role = msg.get('role')
        if role not in ('user', 'assistant', 'toolResult'):
            continue
            
        contents = msg.get('content', [])
        extracted = extract_contents(contents, keep_thinking)
        
        if role == 'user':
            messages.append({"role": "user", "content": extracted.get("content", "")})
        elif role == 'assistant':
            m = {"role": "assistant", "content": extracted.get("content", "")}
            if "reasoning_content" in extracted:
                m["reasoning_content"] = extracted["reasoning_content"]
            if "tool_calls" in extracted:
                m["tool_calls"] = extracted["tool_calls"]
            messages.append(m)
            last_assistant = msg
        elif role == 'toolResult':
            messages.append({
                "role": "tool",
                "tool_call_id": msg.get('toolCallId'),
                "content": extracted.get("content", "")
            })
            
    if not last_assistant:
        return None, "assistant 메시지 없음"
        
    stop_reason = last_assistant.get('stopReason')
    if stop_reason in ('error', 'aborted'):
        return None, f"stopReason이 {stop_reason}"
        
    return messages, None

def main():
    parser = argparse.ArgumentParser(description="세션 JSONL을 SFT 포맷으로 추출")
    parser.add_argument("--sessions-dir", required=True)
    parser.add_argument("--approved", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--keep-thinking", action="store_true")
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
        sys.exit(3)
        
    if not approved_ids:
        sys.exit(3)
        
    samples = []
    missing_ids = set(approved_ids)
    
    sessions_dir = pathlib.Path(args.sessions_dir)
    if sessions_dir.exists():
        for p in sessions_dir.rglob('*.jsonl'):
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
                
            if head.get('type') == 'session' and 'id' in head:
                sid = head['id']
                if sid in approved_ids:
                    missing_ids.discard(sid)
                    try:
                        messages, err = process_session(p, args.keep_thinking)
                        if err:
                            print(f"제외됨 {sid}: {err}", file=sys.stderr)
                        else:
                            samples.append({"session_id": sid, "messages": messages})
                    except Exception as e:
                        print(f"제외됨 {sid}: 예외 발생 - {e}", file=sys.stderr)

    samples.sort(key=lambda x: x["session_id"])
    
    redact_count = [0]
    redacted_samples = redact_recursive(samples, redact_count)
    
    if redacted_samples:
        with open(args.out, 'w', encoding='utf-8') as f:
            for s in redacted_samples:
                f.write(json.dumps(s, ensure_ascii=False) + '\n')
                
    print(f"마스킹 치환 건수: {redact_count[0]}", file=sys.stderr)
    
    if missing_ids:
        for mid in missing_ids:
            print(f"누락된 승인 세션: {mid}", file=sys.stderr)
        sys.exit(2)
        
    if not redacted_samples:
        sys.exit(3)
        
    sys.exit(0)

if __name__ == "__main__":
    main()
