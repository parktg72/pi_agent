"""models.json이 config.env의 포트·alias로 실제로 렌더링되는지 본다."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import render_models_json

TEMPLATE = (Path(__file__).resolve().parents[1] / "win" / "models.json").read_text(encoding="utf-8")


def test_the_rendered_document_uses_the_configured_port_and_alias():
    body, problems = render_models_json.render(TEMPLATE, "18080", "my-alias")
    assert problems == []
    document = json.loads(body)
    assert document["providers"]["local"]["baseUrl"] == "http://127.0.0.1:18080/v1"
    assert [model["id"] for model in document["providers"]["local"]["models"]] == ["my-alias"]


def test_no_placeholder_survives_into_the_output():
    body, problems = render_models_json.render(TEMPLATE, "8080", "qwen3.8-27b")
    assert problems == []
    assert "${" not in body


def test_a_template_that_hardcodes_a_different_port_is_refused():
    # 자리표시자를 지우고 포트를 다시 박아 넣는 돌연변이를 잡는다.
    hardcoded = TEMPLATE.replace("${LLAMA_PORT}", "8080")
    _, problems = render_models_json.render(hardcoded, "18080", "qwen3.8-27b")
    assert any("18080" in problem for problem in problems)


def test_a_template_that_hardcodes_a_different_alias_is_refused():
    hardcoded = TEMPLATE.replace("${MODEL_ALIAS}", "some-other-model")
    _, problems = render_models_json.render(hardcoded, "8080", "qwen3.8-27b")
    assert any("qwen3.8-27b" in problem for problem in problems)


def test_an_unknown_placeholder_is_refused():
    _, problems = render_models_json.render(
        TEMPLATE.replace("${MODEL_ALIAS}", "${NOT_A_VALUE}"), "8080", "a"
    )
    assert problems


def test_a_template_that_is_not_json_after_rendering_is_refused():
    _, problems = render_models_json.render('{"providers": ', "8080", "a")
    assert problems


def test_a_model_id_that_cannot_resolve_in_the_document_is_refused():
    body, problems = render_models_json.render(TEMPLATE, "8080", "qwen3.8-27b")
    assert problems == []
    assert render_models_json.check_model_id(body, "local/qwen3.8-27b") == []
    assert render_models_json.check_model_id(body, "remote/qwen3.8-27b")
    assert render_models_json.check_model_id(body, "local/other")
    assert render_models_json.check_model_id(body, "qwen3.8-27b")


def test_main_writes_the_file_and_returns_zero(tmp_path):
    template = tmp_path / "models.json"
    template.write_text(TEMPLATE, encoding="utf-8")
    out = tmp_path / "home" / "agent" / "models.json"
    code = render_models_json.main(
        [
            "--template", str(template),
            "--out", str(out),
            "--port", "18080",
            "--alias", "qwen3.8-27b",
            "--model-id", "local/qwen3.8-27b",
            "--ctx", "32768",
        ]
    )
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["providers"]["local"]["baseUrl"].endswith(
        ":18080/v1"
    )


def test_main_refuses_a_mismatched_model_id_and_writes_nothing(tmp_path):
    template = tmp_path / "models.json"
    template.write_text(TEMPLATE, encoding="utf-8")
    out = tmp_path / "models.json.out"
    code = render_models_json.main(
        [
            "--template", str(template),
            "--out", str(out),
            "--port", "8080",
            "--alias", "qwen3.8-27b",
            "--model-id", "local/typo",
            "--ctx", "32768",
        ]
    )
    assert code == 1
    assert not out.exists()


def test_main_refuses_a_missing_template(tmp_path):
    assert (
        render_models_json.main(
            [
                "--template", str(tmp_path / "nope.json"),
                "--out", str(tmp_path / "out.json"),
                "--port", "8080",
                "--alias", "a",
                "--ctx", "32768",
            ]
        )
        == 1
    )


# Qwen3.8의 채팅 템플릿이 받는 사고 강도. 템플릿은 이 셋 밖의 값을 만나면
# raise_exception('Unexpected reasoning effort ...')로 생성을 거절한다.
# "off"는 서버로 나가지 않는다 - omitWhenOff가 그 자리를 지운다.
QWEN_REASONING_EFFORTS = {"xhigh", "medium", "low"}


def test_the_local_model_is_declared_as_a_reasoning_model():
    # reasoning이 없으면 Pi는 이 모델을 비추론 모델로 보고 사고 단계 선택지를
    # 아예 만들지 않는다(getSupportedThinkingLevels는 ["off"]만 돌려준다).
    # 그러면 템플릿 기본값 xhigh를 낮출 방법이 사라진다.
    body, problems = render_models_json.render(TEMPLATE, "8080", "qwen3.8-27b")
    assert problems == []
    model = json.loads(body)["providers"]["local"]["models"][0]
    assert model["reasoning"] is True


def test_thinking_kwargs_survive_rendering_as_a_single_dollar_var():
    # 템플릿은 string.Template로 렌더링된다. $var를 그대로 쓰면 자리표시자로
    # 해석돼 렌더링이 실패한다. 원본은 $$var로 적고 결과가 $var여야 한다.
    assert '"$$var"' in TEMPLATE
    body, problems = render_models_json.render(TEMPLATE, "8080", "qwen3.8-27b")
    assert problems == []
    kwargs = json.loads(body)["providers"]["local"]["models"][0]["compat"]["chatTemplateKwargs"]
    assert kwargs["enable_thinking"] == {"$var": "thinking.enabled"}
    assert kwargs["reasoning_effort"] == {"$var": "thinking.effort", "omitWhenOff": True}


def test_the_thinking_map_only_emits_values_the_qwen_template_accepts():
    body, problems = render_models_json.render(TEMPLATE, "8080", "qwen3.8-27b")
    assert problems == []
    model = json.loads(body)["providers"]["local"]["models"][0]
    mapped = model["thinkingLevelMap"]
    for level, value in mapped.items():
        if value is None or level == "off":
            continue
        assert value in QWEN_REASONING_EFFORTS, f"{level} -> {value}"
    # 사고를 끄는 길은 남아 있어야 한다. off가 null이면 목록에서 사라진다.
    assert mapped["off"] is not None
    # 그리고 config.env가 허용하는 단계는 전부 실제로 매핑돼 있어야 한다.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import config_parse

    for level in config_parse.THINKING_LEVELS:
        assert mapped.get(level) is not None, level


def test_the_chat_template_path_is_the_one_pi_uses_for_kwargs():
    # thinkingFormat이 "qwen-chat-template"이면 Pi는 enable_thinking만 보내고
    # chatTemplateKwargs를 무시한다(openai-completions.js:619). 그러면
    # reasoning_effort가 전달되지 않아 템플릿 기본값 xhigh로 되돌아간다.
    body, problems = render_models_json.render(TEMPLATE, "8080", "qwen3.8-27b")
    assert problems == []
    compat = json.loads(body)["providers"]["local"]["models"][0]["compat"]
    assert compat["thinkingFormat"] == "chat-template"
