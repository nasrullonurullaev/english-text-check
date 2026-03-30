import json

from checks import commit_message_advisor_check as advisor


def test_run_skips_advisor_without_api_key(monkeypatch):
    monkeypatch.setattr(advisor, "OPENAI_API_KEY", "")

    result = advisor.run("PR", [{"commit": {"message": "fixed bug"}}], "")

    assert result["feature"] == advisor.FEATURE_KEY
    assert result["is_advisory"] is True
    assert result["comment"] == ""
    assert result["has_violations"] is False


def test_run_returns_empty_on_api_error(monkeypatch):
    monkeypatch.setattr(advisor, "OPENAI_API_KEY", "token")
    monkeypatch.setattr(
        advisor,
        "_responses_api_request",
        lambda payload: (503, "upstream unavailable"),
    )

    result = advisor.run("PR", [{"commit": {"message": "fixed bug"}}], "")

    assert result["is_advisory"] is True
    assert result["comment"] == ""
    assert result["has_violations"] is False


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
