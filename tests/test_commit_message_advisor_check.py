import json

from checks import commit_message_advisor_check as advisor


def test_run_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(advisor, "ADVISOR_ENABLED", False)
    monkeypatch.setattr(advisor, "OPENAI_API_KEY", "")

    result = advisor.run("PR", [{"commit": {"message": "Fix bug"}}], "")

    assert result["feature"] == advisor.FEATURE_KEY
    assert result["is_advisory"] is True
    assert result["has_violations"] is False
    assert result["comment"] == ""


def test_run_uses_heuristics_when_enabled_without_api_key(monkeypatch):
    monkeypatch.setattr(advisor, "ADVISOR_ENABLED", True)
    monkeypatch.setattr(advisor, "OPENAI_API_KEY", "")

    result = advisor.run("PR", [{"commit": {"message": "fixed bug"}}], "")

    assert "recommendations" in result["comment"]
    assert "imperative mood" in result["comment"]
    assert result["is_advisory"] is True
    assert result["has_violations"] is True


def test_run_auto_enables_when_api_key_exists(monkeypatch):
    monkeypatch.setattr(advisor, "ADVISOR_ENABLED", False)
    monkeypatch.setattr(advisor, "OPENAI_API_KEY", "token")
    monkeypatch.setattr(
        advisor,
        "_responses_api_request",
        lambda payload: (503, "upstream unavailable"),
    )

    result = advisor.run("PR", [{"commit": {"message": "fixed bug"}}], "")

    assert result["is_advisory"] is True
    assert result["has_violations"] is True


def test_run_builds_comment_from_model_output(monkeypatch):
    monkeypatch.setattr(advisor, "ADVISOR_ENABLED", True)
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
                                        "score": 42,
                                        "summary": "Use imperative mood and capitalize.",
                                        "suggestions": [
                                            "Start with a capital letter",
                                            "Use imperative mood",
                                        ],
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
    assert "score: 42/100" in result["comment"]
