import os

from checks import commit_message_check as cmc


def test_commit_message_check_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("COMMIT_MESSAGE_AI_CHECK_ENABLED", "true")

    result = cmc.run("", [{"commit": {"message": "fix bug"}}], "")

    assert result["feature"] == cmc.FEATURE_KEY
    assert result["has_violations"] is False
    assert result["commit_violations"] == []


def test_commit_message_check_builds_violations_with_stubbed_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("COMMIT_MESSAGE_AI_CHECK_ENABLED", "true")

    class FakeResponses:
        @staticmethod
        def create(model, input):
            class Resp:
                output_text = (
                    '{"overall_pass": false, "score": 4, "checks": '
                    '[{"rule":"Use the imperative mood in the subject line", '
                    '"passed": false, "details": "Use imperative verb"}], '
                    '"suggested_commit_message": "Fix API timeout", '
                    '"summary": "Needs imperative mood"}'
                )

            return Resp()

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setitem(__import__("sys").modules, "openai", type("M", (), {"OpenAI": FakeOpenAI}))

    commits = [{"sha": "abc123456", "commit": {"message": "fixed timeout"}}]
    result = cmc.run("", commits, "")

    assert result["has_violations"] is True
    assert len(result["commit_violations"]) == 1
    assert "Suggested:" in result["comment"]


def test_commit_message_check_handles_invalid_json(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("COMMIT_MESSAGE_AI_CHECK_ENABLED", "true")

    class FakeResponses:
        @staticmethod
        def create(model, input):
            class Resp:
                output_text = "not-json"

            return Resp()

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = FakeResponses()

    monkeypatch.setitem(__import__("sys").modules, "openai", type("M", (), {"OpenAI": FakeOpenAI}))

    commits = [{"sha": "abc123456", "commit": {"message": "fixed timeout"}}]
    result = cmc.run("", commits, "")

    assert result["has_violations"] is True
    assert result["commit_violations"][0]["score"] == 0
    assert result["commit_violations"][0]["summary"] == "Model did not return valid JSON"
