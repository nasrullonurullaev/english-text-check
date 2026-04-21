import base64
import json
import hmac
import hashlib

import lambda_function as lf
from checks import ai_text_review_check as ai_check


def test_verify_signature_accepts_gitea_header(monkeypatch):
    monkeypatch.setattr(lf, "WEBHOOK_SECRET", "topsecret")
    body = b'{"a":1}'
    digest = hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()

    assert lf.verify_signature(body, {"X-Gitea-Signature": digest}) is True
    assert lf.verify_signature(body, {"X-Gitea-Signature": "bad"}) is False


def test_extract_request_body_base64():
    original = '{"hello":"world"}'
    event = {
        "isBase64Encoded": True,
        "body": base64.b64encode(original.encode("utf-8")).decode("ascii"),
    }

    raw, text = lf.extract_request_body(event)
    assert raw == original.encode("utf-8")
    assert text == original


def test_extract_invalid_pr_title_ignores_non_ascii_inside_quotes():
    title = 'Fix parser for "Привет" string'
    assert lf.extract_invalid_pr_title(title) == []


def test_extract_invalid_pr_title_detects_non_ascii_outside_quotes():
    title = "Исправить parser bug"
    violations = lf.extract_invalid_pr_title(title)
    assert len(violations) == 1
    assert violations[0]["type"] == "pr_title"


def test_extract_non_ascii_comments_detects_violations_and_skips_excluded_files():
    diff = "\n".join(
        [
            "diff --git a/src/main.py b/src/main.py",
            "+++ b/src/main.py",
            "+# Привет мир",
            "diff --git a/docs/readme.md b/docs/readme.md",
            "+++ b/docs/readme.md",
            "+# Привет в md",
        ]
    )

    violations = lf.extract_non_ascii_comments(diff)
    assert len(violations) == 1
    assert violations[0]["file"] == "src/main.py"


def test_lambda_handler_success_path(monkeypatch):
    monkeypatch.setattr(lf, "GITEA_BASE_URL", "https://example.com")
    monkeypatch.setattr(lf, "GITEA_TOKEN", "token")
    monkeypatch.setattr(lf, "WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(lf, "ORG_NAME", "ONLYOFFICE")

    payload = {
        "action": "opened",
        "number": 42,
        "repository": {"name": "repo", "owner": {"login": "ONLYOFFICE"}},
        "pull_request": {
            "number": 42,
            "title": "Fix english text",
            "html_url": "https://example.com/pr/42",
            "head": {"sha": "abc123"},
            "base": {"repo": {"owner": {"login": "ONLYOFFICE"}}},
        },
    }
    body_text = json.dumps(payload)
    raw_body = body_text.encode("utf-8")
    digest = hmac.new(b"secret", raw_body, hashlib.sha256).hexdigest()

    event = {
        "headers": {
            "X-Gitea-Event": "pull_request",
            "X-Gitea-Signature": digest,
        },
        "body": body_text,
        "isBase64Encoded": False,
    }

    calls = []

    def fake_set_commit_status(*args, **kwargs):
        calls.append((args, kwargs))
        return 201, "{}", {}

    monkeypatch.setattr(lf, "set_commit_status", fake_set_commit_status)
    monkeypatch.setattr(lf, "upsert_pr_comment", lambda *args, **kwargs: (201, "{}", {}))
    monkeypatch.setattr(
        lf,
        "fetch_pr_diff",
        lambda owner, repo, pr_number: "diff --git a/a b/a\n+++ b/a\n+// hello",
    )
    monkeypatch.setattr(lf, "fetch_pr_commits", lambda owner, repo, pr_number: [])
    monkeypatch.setattr(
        lf,
        "run_enabled_checks",
        lambda pr_title, commits, diff_text, repo_name="": [
            {
                "feature": "english_text",
                "title_violations": [],
                "commit_violations": [],
                "comment_violations": [],
                "has_violations": False,
                "comment": "",
                "should_comment": False,
            }
        ],
    )

    result = lf.lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["ok"] is True
    assert body["status_state"] == "success"
    assert len(calls) == 2


def test_run_enabled_checks_normalizes_result(monkeypatch):
    class BadCheck:
        @staticmethod
        def run(pr_title, commits, diff_text):
            return {"feature": "custom"}

    monkeypatch.setattr(lf, "get_enabled_checks", lambda: [BadCheck])

    results = lf.run_enabled_checks("title", [], "diff --git a/a b/a")
    assert len(results) == 1
    result = results[0]
    assert result["feature"] == "custom"
    assert result["title_violations"] == []
    assert result["commit_violations"] == []
    assert result["comment_violations"] == []
    assert result["has_violations"] is False
    assert result["comment"] == ""


def test_run_enabled_checks_skips_ai_for_non_whitelisted_repo(monkeypatch):
    class EnglishCheck:
        FEATURE_KEY = "english_text"

        @staticmethod
        def run(pr_title, commits, diff_text):
            return {"feature": "english_text"}

    class AiCheck:
        FEATURE_KEY = "ai_text_review"

        @staticmethod
        def run(pr_title, commits, diff_text):
            return {"feature": "ai_text_review"}

    monkeypatch.setattr(lf, "get_enabled_checks", lambda: [EnglishCheck, AiCheck])
    monkeypatch.setattr(lf, "AI_REPOSITORY_WHITELIST", {"DocSpace-buildtools"})

    results = lf.run_enabled_checks(
        "title",
        [],
        "diff --git a/a b/a",
        repo_name="some-other-repo",
    )
    assert len(results) == 1
    assert results[0]["feature"] == "english_text"


def test_run_enabled_checks_includes_ai_for_whitelisted_repo(monkeypatch):
    class EnglishCheck:
        FEATURE_KEY = "english_text"

        @staticmethod
        def run(pr_title, commits, diff_text):
            return {"feature": "english_text"}

    class AiCheck:
        FEATURE_KEY = "ai_text_review"

        @staticmethod
        def run(pr_title, commits, diff_text):
            return {"feature": "ai_text_review"}

    monkeypatch.setattr(lf, "get_enabled_checks", lambda: [EnglishCheck, AiCheck])
    monkeypatch.setattr(lf, "AI_REPOSITORY_WHITELIST", {"DocSpace-buildtools"})

    results = lf.run_enabled_checks(
        "title",
        [],
        "diff --git a/a b/a",
        repo_name="DocSpace-buildtools",
    )
    assert len(results) == 2
    assert results[0]["feature"] == "english_text"
    assert results[1]["feature"] == "ai_text_review"


def test_aggregate_english_result_fallback():
    result = lf.aggregate_english_result([{"feature": "other"}])
    assert result["title_violations"] == []
    assert result["commit_violations"] == []
    assert result["comment_violations"] == []
    assert result["has_violations"] is False
    assert result["comment"] == ""


def test_aggregate_check_results_collects_all_and_comments():
    results = [
        {
            "feature": "a",
            "title_violations": [{"type": "x"}],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": True,
            "comment": "comment-a",
            "should_comment": True,
        },
        {
            "feature": "b",
            "title_violations": [],
            "commit_violations": [{"type": "y"}],
            "comment_violations": [{"type": "z"}],
            "has_violations": True,
            "comment": "comment-b",
            "should_comment": False,
        },
    ]

    aggregated = lf.aggregate_check_results(results)

    assert aggregated["has_violations"] is True
    assert len(aggregated["title_violations"]) == 1
    assert len(aggregated["commit_violations"]) == 1
    assert len(aggregated["comment_violations"]) == 1
    assert aggregated["comment"] == "comment-a"


def test_lambda_handler_posts_comment_when_check_requests_it(monkeypatch):
    monkeypatch.setattr(lf, "GITEA_BASE_URL", "https://example.com")
    monkeypatch.setattr(lf, "GITEA_TOKEN", "token")
    monkeypatch.setattr(lf, "WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(lf, "ORG_NAME", "ONLYOFFICE")

    payload = {
        "action": "opened",
        "number": 42,
        "repository": {"name": "repo", "owner": {"login": "ONLYOFFICE"}},
        "pull_request": {
            "number": 42,
            "title": "Fix english text",
            "html_url": "https://example.com/pr/42",
            "head": {"sha": "abc123"},
            "base": {"repo": {"owner": {"login": "ONLYOFFICE"}}},
        },
    }
    body_text = json.dumps(payload)
    raw_body = body_text.encode("utf-8")
    digest = hmac.new(b"secret", raw_body, hashlib.sha256).hexdigest()

    event = {
        "headers": {
            "X-Gitea-Event": "pull_request",
            "X-Gitea-Signature": digest,
        },
        "body": body_text,
        "isBase64Encoded": False,
    }

    status_calls = []
    comment_calls = []

    def fake_set_commit_status(*args, **kwargs):
        status_calls.append((args, kwargs))
        return 201, "{}", {}

    def fake_upsert_pr_comment(*args, **kwargs):
        comment_calls.append((args, kwargs))
        return 201, "{}", {}

    monkeypatch.setattr(lf, "set_commit_status", fake_set_commit_status)
    monkeypatch.setattr(lf, "upsert_pr_comment", fake_upsert_pr_comment)
    monkeypatch.setattr(
        lf,
        "fetch_pr_diff",
        lambda owner, repo, pr_number: "diff --git a/a b/a\n+++ b/a\n+// hello",
    )
    monkeypatch.setattr(lf, "fetch_pr_commits", lambda owner, repo, pr_number: [])
    monkeypatch.setattr(
        lf,
        "run_enabled_checks",
        lambda pr_title, commits, diff_text, repo_name="": [
            {
                "feature": "ai_text_review",
                "title_violations": [],
                "commit_violations": [],
                "comment_violations": [],
                "has_violations": False,
                "comment": "✅ Everything is OK",
                "should_comment": True,
            }
        ],
    )

    result = lf.lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["ok"] is True
    assert body["status_state"] == "success"
    assert len(status_calls) == 2
    assert len(comment_calls) == 1


def test_upsert_pr_comment_updates_existing_managed_comment(monkeypatch):
    monkeypatch.setattr(
        lf,
        "list_pr_comments",
        lambda owner, repo, pr_number: (
            200,
            "[]",
            {},
            [{"id": 5, "body": "old\n\n{0}".format(lf.COMMENT_MARKER)}],
        ),
    )
    edited = []
    monkeypatch.setattr(
        lf,
        "edit_issue_comment",
        lambda owner, repo, comment_id, text: edited.append((comment_id, text)) or (200, "{}", {}),
    )
    monkeypatch.setattr(
        lf,
        "post_pr_comment",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create a new comment")),
    )

    status, _, _ = lf.upsert_pr_comment("ONLYOFFICE", "repo", 1, "new body")
    assert status == 200
    assert edited[0][0] == 5
    assert lf.COMMENT_MARKER in edited[0][1]


def test_upsert_pr_comment_creates_when_no_managed_comment(monkeypatch):
    monkeypatch.setattr(
        lf,
        "list_pr_comments",
        lambda owner, repo, pr_number: (200, "[]", {}, [{"id": 7, "body": "random comment"}]),
    )
    created = []
    monkeypatch.setattr(
        lf,
        "post_pr_comment",
        lambda owner, repo, pr_number, text: created.append((pr_number, text)) or (201, "{}", {}),
    )

    status, _, _ = lf.upsert_pr_comment("ONLYOFFICE", "repo", 42, "new body")
    assert status == 201
    assert created[0][0] == 42
    assert lf.COMMENT_MARKER in created[0][1]


def test_ai_text_review_is_advisory_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = ai_check.run(pr_title="test", commits=[], diff_text="")

    assert result["has_violations"] is False
    assert "skipped" in result["comment"].lower()
    assert result["should_comment"] is True


def test_ai_text_review_comment_uses_advice_wording():
    pr_title_result = {
        "overall_pass": False,
        "summary": "Use imperative mood.",
        "suggested_commit_message": "Set default branch to master",
    }
    commit_results = [
        {
            "overall_pass": False,
            "subject": "fix: bad title",
            "summary": "Capitalize the subject.",
            "suggested_commit_message": "Fix bad title",
        }
    ]

    comment = ai_check._build_comment(pr_title_result, commit_results)
    assert "💡 PR title: improvement suggestion." in comment
    assert "💡 Commit messages: 1 suggestion(s)." in comment


def test_ai_check_requires_openai_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = ai_check.run(pr_title="Fix title", commits=[], diff_text="")

    assert result["has_violations"] is False
    assert result["should_comment"] is True
    assert result["title_violations"] == []
