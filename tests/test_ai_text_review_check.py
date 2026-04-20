import json
import sys
import types

from checks import ai_text_review_check as ai_check


class _FakeResponses:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = 0

    def create(self, **kwargs):
        del kwargs
        payload = self.payloads[self.calls]
        self.calls += 1

        class _Resp:
            def __init__(self, text):
                self.output_text = text

        return _Resp(payload)


class _FakeOpenAI:
    def __init__(self, api_key, payloads):
        del api_key
        self.responses = _FakeResponses(payloads)


def test_run_fails_closed_on_openai_runtime_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "token")

    class _BrokenOpenAI:
        def __init__(self, api_key):
            del api_key
            raise RuntimeError("network down")

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_BrokenOpenAI))

    result = ai_check.run(pr_title="Fix title", commits=[], diff_text="")

    assert result["has_violations"] is True
    assert result["title_violations"][0]["type"] == "ai_review_runtime_error"
    assert "failed" in result["comment"].lower()


def test_run_trims_long_text_and_reviews(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "token")

    payload = json.dumps(
        {
            "overall_pass": True,
            "score": 100,
            "subject": "Fix title",
            "body_present": False,
            "checks": [],
            "suggested_commit_message": "",
            "summary": "Looks good",
        }
    )

    class _InjectedOpenAI:
        def __init__(self, api_key):
            self.inner = _FakeOpenAI(api_key, [payload, payload])
            self.responses = self.inner.responses

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_InjectedOpenAI))
    monkeypatch.setattr(ai_check, "MAX_TITLE_CHARS", 10)
    monkeypatch.setattr(ai_check, "MAX_COMMIT_MESSAGE_CHARS", 12)

    result = ai_check.run(
        pr_title="A" * 40,
        commits=[{"commit": {"message": "B" * 60}}],
        diff_text="",
    )

    assert result["has_violations"] is False
    assert result["should_comment"] is True
    assert "AI text review" in result["comment"]


def test_review_text_retries_and_then_fails(monkeypatch):
    class _AlwaysFailResponses:
        def create(self, **kwargs):
            del kwargs
            raise RuntimeError("temporary error")

    class _Client:
        responses = _AlwaysFailResponses()

    monkeypatch.setattr(ai_check, "OPENAI_MAX_RETRIES", 1)
    monkeypatch.setattr(ai_check, "OPENAI_RETRY_DELAY_SECONDS", 0)

    try:
        ai_check._review_text(_Client(), "git commit message", "Fix bug")
        assert False, "Expected RuntimeError"
    except RuntimeError:
        assert True
