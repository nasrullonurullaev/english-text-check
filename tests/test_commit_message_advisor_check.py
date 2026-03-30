import json

from checks import commit_message_advisor_check as advisor


def test_run_returns_error_without_api_key(monkeypatch):
    monkeypatch.setattr(advisor, "OPENAI_API_KEY", "")

    result = advisor.run("PR", [{"commit": {"message": "Обновить docker-bake.hcl"}}], "")

    assert result["feature"] == advisor.FEATURE_KEY
    assert result["is_advisory"] is True
    assert "OPENAI_API_KEY is not configured" in result["comment"]
    assert result["has_violations"] is True


def test_run_returns_error_on_api_error(monkeypatch):
    monkeypatch.setattr(advisor, "OPENAI_API_KEY", "token")
    monkeypatch.setattr(
        advisor,
        "_responses_api_request",
        lambda payload: (503, "upstream unavailable"),
    )

    result = advisor.run("PR", [{"commit": {"message": "fixed bug"}}], "")

    assert result["is_advisory"] is True
    assert "request failed with status 503" in result["comment"]
    assert result["has_violations"] is True


def test_run_builds_comment_from_model_output(monkeypatch):
    monkeypatch.setattr(advisor, "OPENAI_API_KEY", "token")

    model_output = {
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "analysis": [
                                    {
                                        "subject": "fixed stuff",
                                        "verdict": "rewrite",
                                        "suggested_subject": "Fix stuff",
                                        "reason": "Use imperative mood and capitalize.",
                                    }
                                ]
                            }
                        ),
                    }
                ]
            }
        ]
    }

    monkeypatch.setattr(
        advisor,
        "_responses_api_request",
        lambda payload: (200, json.dumps(model_output)),
    )

    commits = [{"commit": {"message": "fixed stuff\n\nmade changes"}}]
    result = advisor.run("Improve checks", commits, "")

    assert result["has_violations"] is True
    assert result["is_advisory"] is True
    assert "non-blocking" in result["comment"]
    assert "Fix stuff" in result["comment"]


def test_run_parses_markdown_wrapped_json(monkeypatch):
    monkeypatch.setattr(advisor, "OPENAI_API_KEY", "token")

    wrapped = {
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            "Here is the result:\n```json\n"
                            "{\"analysis\":[{\"subject\":\"Update docker-bake.hcl\","
                            "\"verdict\":\"ok\",\"suggested_subject\":\"\",\"reason\":\"\"}]}\n"
                            "```"
                        ),
                    }
                ]
            }
        ]
    }

    monkeypatch.setattr(
        advisor,
        "_responses_api_request",
        lambda payload: (200, json.dumps(wrapped)),
    )

    commits = [{"commit": {"message": "Update docker-bake.hcl"}}]
    result = advisor.run("Improve checks", commits, "")

    assert result["has_violations"] is True
    assert "✅ OK" in result["comment"]
