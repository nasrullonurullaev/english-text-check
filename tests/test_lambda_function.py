import base64
import json
import hmac
import hashlib

import pytest
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
            "base": {"ref": "release/v1", "repo": {"owner": {"login": "ONLYOFFICE"}}},
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
        lambda pr_title, commits, diff_text, repo_name="", base_branch="", pr_comments=None: [
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


def test_run_enabled_checks_normalizes_non_list_violations(monkeypatch):
    class BadCheck:
        @staticmethod
        def run(pr_title, commits, diff_text):
            return {
                "feature": "custom",
                "title_violations": "bad-type",
                "commit_violations": {"kind": "x"},
                "comment_violations": ("tuple-item",),
            }

    monkeypatch.setattr(lf, "get_enabled_checks", lambda: [BadCheck])

    results = lf.run_enabled_checks("title", [], "diff --git a/a b/a")
    result = results[0]

    assert result["title_violations"] == []
    assert result["commit_violations"] == []
    assert result["comment_violations"] == ["tuple-item"]


def test_run_enabled_checks_runs_ai_for_any_repo(monkeypatch):
    class AiCheck:
        FEATURE_KEY = "ai_text_review"

        @staticmethod
        def run(pr_title, commits, diff_text):
            return {"feature": "ai_text_review"}

    monkeypatch.setattr(lf, "get_enabled_checks", lambda: [AiCheck])
    results = lf.run_enabled_checks(
        "title",
        [],
        "diff --git a/a b/a",
        repo_name="some-other-repo",
    )
    assert len(results) == 1
    assert results[0]["feature"] == "ai_text_review"


def test_run_enabled_checks_passes_optional_arguments_to_ai(monkeypatch):
    class AiCheck:
        FEATURE_KEY = "ai_text_review"

        @staticmethod
        def run(pr_title, commits, diff_text, base_branch="", pr_comments=None):
            assert base_branch == "release/v1"
            assert pr_comments == [{"id": 1, "body": "old comment"}]
            return {"feature": "ai_text_review"}

    monkeypatch.setattr(lf, "get_enabled_checks", lambda: [AiCheck])

    results = lf.run_enabled_checks(
        "title",
        [],
        "diff --git a/a b/a",
        repo_name="any-repo",
        base_branch="release/v1",
        pr_comments=[{"id": 1, "body": "old comment"}],
    )
    assert len(results) == 1
    assert results[0]["feature"] == "ai_text_review"


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
            "base": {"ref": "release/v1", "repo": {"owner": {"login": "ONLYOFFICE"}}},
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
        lambda pr_title, commits, diff_text, repo_name="", base_branch="", pr_comments=None: [
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
    pytest.importorskip("anthropic")
    from checks import ai_text_review_check as ai_check

    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    result = ai_check.run(pr_title="test", commits=[], diff_text="")

    assert result["has_violations"] is False
    assert "skipped" in result["comment"].lower()
    assert result["should_comment"] is True


def test_extract_verdict_recognizes_blocked():
    pytest.importorskip("anthropic")
    from checks import ai_text_review_check as ai_check

    verdict = ai_check._extract_verdict("<summary>❌ BLOCKED - Claude Code Review</summary>")
    assert verdict == "blocked"


def test_ai_check_requires_claude_api_key(monkeypatch):
    pytest.importorskip("anthropic")
    from checks import ai_text_review_check as ai_check

    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)

    result = ai_check.run(pr_title="Fix title", commits=[], diff_text="")

    assert result["has_violations"] is False
    assert result["should_comment"] is True
    assert result["title_violations"] == []


def test_is_repository_allowed_with_empty_whitelist():
    assert lf.is_repository_allowed("ONLYOFFICE", "repo", set()) is True


def test_is_repository_allowed_matches_name_and_full_name():
    assert lf.is_repository_allowed("ONLYOFFICE", "repo", {"repo"}) is True
    assert lf.is_repository_allowed("ONLYOFFICE", "repo", {"ONLYOFFICE/repo"}) is True
    assert lf.is_repository_allowed("ONLYOFFICE", "repo", {"another"}) is False


def test_is_base_branch_allowed_matches_release_hotfix_patterns():
    patterns = ("release/*", "hotfix/*")
    assert lf.is_base_branch_allowed("release/8.4.1", patterns) is True
    assert lf.is_base_branch_allowed("hotfix/urgent-fix", patterns) is True
    assert lf.is_base_branch_allowed("main", patterns) is False


def test_lambda_handler_ignores_disallowed_repository(monkeypatch):
    monkeypatch.setattr(lf, "GITEA_BASE_URL", "https://example.com")
    monkeypatch.setattr(lf, "GITEA_TOKEN", "token")
    monkeypatch.setattr(lf, "WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(lf, "ORG_NAME", "ONLYOFFICE")
    monkeypatch.setattr(lf, "ALLOWED_REPOSITORIES", {"ONLYOFFICE/allowed-repo"})

    payload = {
        "action": "opened",
        "number": 1,
        "repository": {"name": "blocked-repo", "owner": {"login": "ONLYOFFICE"}},
        "pull_request": {
            "number": 1,
            "title": "Fix english text",
            "html_url": "https://example.com/pr/1",
            "head": {"sha": "abc123"},
            "base": {"ref": "release/v1", "repo": {"owner": {"login": "ONLYOFFICE"}}},
        },
    }
    body_text = json.dumps(payload)
    digest = hmac.new(b"secret", body_text.encode("utf-8"), hashlib.sha256).hexdigest()

    event = {
        "headers": {
            "X-Gitea-Event": "pull_request",
            "X-Gitea-Signature": digest,
        },
        "body": body_text,
        "isBase64Encoded": False,
    }

    result = lf.lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["ignored"] is True
    assert body["reason"] == "repository not allowed"


def test_lambda_handler_ignores_disallowed_base_branch(monkeypatch):
    monkeypatch.setattr(lf, "GITEA_BASE_URL", "https://example.com")
    monkeypatch.setattr(lf, "GITEA_TOKEN", "token")
    monkeypatch.setattr(lf, "WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(lf, "ORG_NAME", "ONLYOFFICE")

    payload = {
        "action": "opened",
        "number": 1,
        "repository": {"name": "repo", "owner": {"login": "ONLYOFFICE"}},
        "pull_request": {
            "number": 1,
            "title": "Fix english text",
            "html_url": "https://example.com/pr/1",
            "head": {"sha": "abc123"},
            "base": {"ref": "main", "repo": {"owner": {"login": "ONLYOFFICE"}}},
        },
    }
    body_text = json.dumps(payload)
    digest = hmac.new(b"secret", body_text.encode("utf-8"), hashlib.sha256).hexdigest()

    event = {
        "headers": {
            "X-Gitea-Event": "pull_request",
            "X-Gitea-Signature": digest,
        },
        "body": body_text,
        "isBase64Encoded": False,
    }

    result = lf.lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["ignored"] is True
    assert body["reason"] == "base branch not allowed"
