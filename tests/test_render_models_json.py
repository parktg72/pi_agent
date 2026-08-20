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
            ]
        )
        == 1
    )
