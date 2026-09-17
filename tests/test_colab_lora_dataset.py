"""colab-lora/dataset.py — train_indices 샘플을 학습 시퀀스로 바꾸는 규칙(C단계 합의 2·3·7).

실제 Qwen3.8 토크나이저 대신 "\\n\\n"을 한 토큰으로 합치는 장난감 토크나이저를 쓴다. 실 토크나이저에서
관찰한 경계 병합(sources/c-tokenization-finding.md)을 같은 모양으로 재현해, 대상별 prefix 검사와
별도 시퀀스 경로를 고정한다. 렌더는 번들 GGUF 템플릿 그대로(jinja2).
"""
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("colab_lora_dataset", ROOT / "colab-lora" / "dataset.py")
dataset = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dataset  # dataclass가 모듈을 sys.modules에서 찾는다
spec.loader.exec_module(dataset)

TEMPLATE = (ROOT / "colab-lora" / "qwen38_chat_template.jinja").read_text(encoding="utf-8")
SPECIAL = re.compile(r"<\|im_start\|>|<\|im_end\|>|<think>|</think>|<tool_call>|</tool_call>|\n\n|.", re.S)


class ToyTokenizer:
    def __init__(self):
        self.vocab, self.inverse = {}, {}

    def encode(self, text):
        ids = []
        for piece in SPECIAL.findall(text):
            if piece not in self.vocab:
                self.vocab[piece] = len(self.vocab)
                self.inverse[self.vocab[piece]] = piece
            ids.append(self.vocab[piece])
        return ids

    def decode(self, ids):
        return "".join(self.inverse[i] for i in ids)


def jinja_render():
    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    env.globals["raise_exception"] = lambda message: (_ for _ in ()).throw(jinja2.TemplateError(message))
    env.filters["tojson"] = lambda value, **_: json.dumps(value, ensure_ascii=False)
    template = env.from_string(TEMPLATE)

    def render(messages, sample, generation):
        return template.render(messages=messages, tools=sample["tools"] or None, add_generation_prompt=generation,
                               **sample["chat_template_kwargs"])

    return render


def sample(**overrides):
    base = {
        "session_id": "s1", "segment": 0, "tokens": 100, "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "medium"},
        "tools": [{"type": "function", "function": {"name": "read", "description": "Read", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}],
        "messages": [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "reasoning_content": "plan", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": {"path": "a.txt"}}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "DATA"},
            {"role": "assistant", "content": "answer", "reasoning_content": "done"},
        ],
        "train_indices": [2, 4],
    }
    base.update(overrides)
    return base


def build(s, max_seq_len=10_000):
    tok = ToyTokenizer()
    sequences, stats = dataset.build_sequences(s, jinja_render(), tok.encode, max_seq_len)
    return tok, sequences, stats


def test_labels_are_exactly_the_generated_replies_including_im_end():
    tok, sequences, stats = build(sample())
    assert (stats.shared_targets, stats.separate_targets, stats.sequences) == (2, 0, 1)
    shared = sequences[0]
    labelled = tok.decode([l for l in shared.labels if l != dataset.IGNORE])
    assert labelled == ("plan\n</think>\n\n<tool_call>\n<function=read>\n<parameter=path>\na.txt\n</parameter>\n</function>\n</tool_call><|im_end|>"
                        "done\n</think>\n\nanswer<|im_end|>")
    # 대상 앞은 요청 prefix 전체 토큰화와 같고, 시퀀스는 마지막 대상에서 끝난다.
    render = jinja_render()
    prefix = render(sample()["messages"][:4], sample(), True)
    assert shared.input_ids[:len(tok.encode(prefix))] == tok.encode(prefix)
    assert tok.decode(shared.input_ids).endswith("answer<|im_end|>")


def test_context_replies_before_the_segment_are_not_trained():
    tok, sequences, stats = build(sample(train_indices=[4]))
    labelled = tok.decode([l for l in sequences[0].labels if l != dataset.IGNORE])
    assert labelled == "done\n</think>\n\nanswer<|im_end|>"
    assert "plan" in tok.decode(sequences[0].input_ids)


def test_empty_reasoning_before_a_later_target_moves_that_target_to_its_own_sequence():
    s = sample()
    del s["messages"][2]["reasoning_content"]  # "<think>\n" + "\n</think>" -> 전체 토큰화에서 "\n\n" 병합
    tok, sequences, stats = build(s)
    assert (stats.shared_targets, stats.separate_targets) == (1, 1)
    shared, separate = sequences
    assert tok.decode([l for l in shared.labels if l != dataset.IGNORE]).startswith("\n</think>")
    prefix = jinja_render()(s["messages"][:4], s, True)
    assert separate.kind == "separate"
    assert separate.input_ids[:len(tok.encode(prefix))] == tok.encode(prefix)
    assert tok.decode([l for l in separate.labels if l != dataset.IGNORE]) == "done\n</think>\n\nanswer<|im_end|>"


def test_targets_over_the_length_limit_are_held_back_not_truncated():
    _, full, _ = build(sample())
    limit = len(full[0].input_ids) - 1
    tok, sequences, stats = build(sample(), max_seq_len=limit)
    assert (stats.shared_targets, stats.over_length_targets) == (1, 1)
    assert tok.decode(sequences[0].input_ids).endswith("</tool_call><|im_end|>")

    _, sequences, stats = build(sample(), max_seq_len=5)
    assert (sequences, stats.over_length_targets) == ([], 2)


def test_sessions_not_segments_are_held_out():
    samples = [sample(session_id=f"s{i}", segment=j) for i in range(10) for j in range(2)]
    train, held = dataset.split_sessions(samples, 0.1)
    held_sessions = {s["session_id"] for s in held}
    assert len(held_sessions) == 1 and len(held) == 2
    assert not held_sessions & {s["session_id"] for s in train}
    assert dataset.split_sessions(samples, 0.1) == (train, held)
    assert dataset.split_sessions([sample()], 0.1) == ([sample()], [])


def test_bad_rows_and_templates_are_refused(tmp_path):
    bad = sample(train_indices=[3])
    path = tmp_path / "train.jsonl"
    path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(dataset.DataError, match="assistant"):
        dataset.load_samples(path)
    old = copy.deepcopy(sample())
    del old["train_indices"]
    path.write_text(json.dumps(old) + "\n", encoding="utf-8")
    with pytest.raises(dataset.DataError, match="v2"):
        dataset.load_samples(path)
    with pytest.raises(dataset.DataError, match="sha256"):
        dataset.check_template(TEMPLATE + " ")
    assert dataset.check_template(TEMPLATE) == dataset.EXPECTED_TEMPLATE_SHA256


def test_exporter_fixture_samples_build_without_errors(tmp_path):
    import subprocess, shutil
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    shutil.copy(ROOT / "tests" / "fixtures" / "pi_session_0851_lora_snapshot.jsonl", sessions / "s.jsonl")
    approved = tmp_path / "approved.txt"
    approved.write_text("01a0af3d-bf83-77b5-9a13-538b10ed1683\n")
    out = tmp_path / "train.jsonl"
    res = subprocess.run([sys.executable, "tools/export_sessions.py", "--sessions-dir", str(sessions), "--approved", str(approved), "--out", str(out)],
                         capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    assert res.returncode == 0, res.stderr
    render, tok = jinja_render(), ToyTokenizer()
    sequences, stats = dataset.build_all(dataset.load_samples(out), render, tok.encode, 100_000)
    assert (stats.samples, stats.targets, stats.shared_targets + stats.separate_targets) == (2, 4, 4)
    assert all(tok.decode(s.input_ids).endswith("<|im_end|>") for s in sequences)


def test_tools_are_reduced_to_what_llama_server_passes_to_the_template():
    # common/chat.cpp common_chat_tools_to_json_oaicompat (b11010): type·function{name, description, parameters}만.
    # Pi가 보내는 "strict": false를 학습 렌더에 남기면 추론 렌더와 달라진다(template_parity.py 실측).
    tools = [{"type": "function", "function": {"name": "read", "description": "R", "parameters": {"type": "object"}, "strict": False}},
             {"type": "function", "function": {"name": "bare"}}]
    assert dataset.server_tools(tools) == [
        {"type": "function", "function": {"name": "read", "description": "R", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "bare", "description": "", "parameters": {}}},
    ]
    assert list(dataset.server_tools(tools)[0]["function"]) == ["name", "description", "parameters"]
    assert dataset.server_tools([]) is None


def test_a_quoted_im_end_inside_a_reply_does_not_cut_the_target():
    s = sample()
    s["messages"][4]["content"] = "템플릿은 <|im_end|> 로 끝난다. 계속"
    tok, sequences, _ = build(s)
    labelled = tok.decode([l for l in sequences[0].labels if l != dataset.IGNORE])
    assert labelled.endswith("템플릿은 <|im_end|> 로 끝난다. 계속<|im_end|>")


def test_context_that_changes_between_requests_starts_a_new_shared_sequence():
    # preserve_thinking=false면 다음 요청에서 과거 reasoning이 사라져 앞 문맥이 달라진다 - 데이터 오류가 아니다.
    s = sample(chat_template_kwargs={"enable_thinking": True, "reasoning_effort": "medium", "preserve_thinking": False})
    s["messages"].insert(5, {"role": "user", "content": "more"})
    s["messages"].append({"role": "assistant", "content": "second", "reasoning_content": "again"})
    s["train_indices"] = [4, 6]
    tok, sequences, stats = build(s)
    assert (stats.targets, stats.shared_targets + stats.separate_targets) == (2, 2)
    assert [q.kind for q in sequences].count("shared") == 2
    render = jinja_render()
    prefix = render(s["messages"][:6], s, True)
    second = sequences[1]
    assert second.input_ids[:len(tok.encode(prefix))] == tok.encode(prefix)
