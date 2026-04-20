import checks.ai_text_review_check as ai


class _FakeResponse:
    def __init__(self, text):
        self.output_text = text


class _FakeClient:
    def __init__(self):
        self.calls = []

        class _Responses:
            def __init__(self, outer):
                self.outer = outer

            def create(self, **kwargs):
                self.outer.calls.append(kwargs)
                return _FakeResponse(
                    '{"overall_pass": true, "score": 100, "subject": "OK", '
                    '"body_present": false, "checks": [], '
                    '"suggested_commit_message": "", "summary": "Looks good"}'
                )

        self.responses = _Responses(self)


def test_run_reviews_all_commits(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    fake_client = _FakeClient()

    monkeypatch.setitem(__import__("sys").modules, "openai", type("M", (), {"OpenAI": lambda **kwargs: fake_client}))

    commits = [
        {"commit": {"message": "First"}},
        {"commit": {"message": "Second"}},
        {"commit": {"message": "Third"}},
    ]

    result = ai.run("Title", commits, "")

    assert result["feature"] == ai.FEATURE_KEY
    assert len(fake_client.calls) == 4  # 1 for title + 3 commits
