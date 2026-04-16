import base64
import json
import hmac
import hashlib

import lambda_function as lf


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
    monkeypatch.setattr(
        lf,
        "fetch_pr_diff",
        lambda owner, repo, pr_number: "diff --git a/a b/a\n+++ b/a\n+// hello",
    )
    monkeypatch.setattr(lf, "fetch_pr_commits", lambda owner, repo, pr_number: [])

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


def test_aggregate_english_result_fallback():
    result = lf.aggregate_english_result([{"feature": "other"}])
    assert result["title_violations"] == []
    assert result["commit_violations"] == []
    assert result["comment_violations"] == []
    assert result["has_violations"] is False
    assert result["comment"] == ""


def test_aggregate_check_results_merges_comments_and_violations():
    check_results = [
        {
            "feature": "english_text",
            "title_violations": [{"type": "pr_title"}],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": True,
            "comment": "english issues",
        },
        {
            "feature": "commit_message_quality",
            "title_violations": [],
            "commit_violations": [{"type": "commit_message_quality"}],
            "comment_violations": [],
            "has_violations": True,
            "comment": "commit issues",
        },
    ]

    result = lf.aggregate_check_results(check_results)

    assert result["has_violations"] is True
    assert len(result["title_violations"]) == 1
    assert len(result["commit_violations"]) == 1
    assert "---" in result["comment"]
