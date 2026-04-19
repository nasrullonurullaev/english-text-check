import os
import json
import hmac
import hashlib
import base64
import urllib.request
import urllib.error

from checks import get_enabled_checks
from checks import english_text_check


GITEA_BASE_URL = os.getenv("GITEA_BASE_URL", "").rstrip("/")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
ORG_NAME = os.getenv("ORG_NAME", "ONLYOFFICE")
STATUS_CONTEXT = os.getenv("STATUS_CONTEXT", "English-Text-Check")

ALLOWED_ACTIONS = set(
    x.strip()
    for x in os.getenv(
        "ALLOWED_ACTIONS",
        "opened,reopened,synchronize,edited,synchronized"
    ).split(",")
    if x.strip()
)

REQUIRED_CHECK_FIELDS = (
    "feature",
    "title_violations",
    "commit_violations",
    "comment_violations",
    "has_violations",
    "comment",
)

OPTIONAL_CHECK_FIELDS = (
    "always_comment",
)


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def normalize_headers(headers):
    if not headers:
        return {}
    return {str(k).lower(): str(v) for k, v in headers.items()}


def verify_signature(raw_body, headers):
    if not WEBHOOK_SECRET:
        return False

    lower = normalize_headers(headers)

    sig_gitea = lower.get("x-gitea-signature")
    sig_gogs = lower.get("x-gogs-signature")
    sig_hub_256 = lower.get("x-hub-signature-256")

    digest = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    valid_values = [digest, "sha256=" + digest]

    for sig in (sig_gitea, sig_gogs, sig_hub_256):
        if not sig:
            continue
        for expected in valid_values:
            if hmac.compare_digest(sig, expected):
                return True

    return False


def http_request(method, url, payload=None, accept="application/json"):
    headers = {
        "Authorization": "token " + GITEA_TOKEN,
        "Accept": accept,
        "User-Agent": "gitea-english-text-check-lambda",
    }

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body, dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body, dict(e.headers)
    except Exception as e:
        return 599, str(e), {}


def gitea_api_request(method, path, payload=None, accept="application/json"):
    if not GITEA_BASE_URL or not GITEA_TOKEN:
        return 599, "Missing GITEA_BASE_URL or GITEA_TOKEN", {}

    url = GITEA_BASE_URL + path
    return http_request(method, url, payload=payload, accept=accept)


def post_pr_comment(owner, repo, pr_number, text):
    path = "/api/v1/repos/{owner}/{repo}/issues/{pr_number}/comments".format(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
    )
    return gitea_api_request("POST", path, {"body": text})


def set_commit_status(owner, repo, sha, state, description, target_url=""):
    path = "/api/v1/repos/{owner}/{repo}/statuses/{sha}".format(
        owner=owner,
        repo=repo,
        sha=sha,
    )

    payload = {
        "state": state,
        "context": STATUS_CONTEXT,
        "description": description[:140],
    }

    if target_url:
        payload["target_url"] = target_url

    return gitea_api_request("POST", path, payload)


def is_org_pr(payload, org_name):
    pr = payload.get("pull_request") or {}
    base = pr.get("base") or {}
    base_repo = base.get("repo") or {}

    base_owner = ((base_repo.get("owner") or {}).get("login")) or ""
    parent_repo = base_repo.get("parent") or {}
    parent_owner = ((parent_repo.get("owner") or {}).get("login")) or ""

    return base_owner == org_name or parent_owner == org_name


def extract_request_body(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(body)
        body_text = raw_body.decode("utf-8")
    else:
        body_text = body
        raw_body = body_text.encode("utf-8")
    return raw_body, body_text


def fetch_pr_diff(owner, repo, pr_number):
    path = "/api/v1/repos/{owner}/{repo}/pulls/{pr_number}.diff".format(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
    )
    status, body, _ = gitea_api_request("GET", path, accept="text/plain")

    if status >= 300:
        raise ValueError(
            "failed to fetch PR diff: status={0}, body={1}".format(status, body[:500])
        )

    if "diff --git " not in body and "@@ " not in body:
        raise ValueError("PR diff API did not return a valid patch/diff")

    return body


def fetch_pr_commits(owner, repo, pr_number):
    path = "/api/v1/repos/{owner}/{repo}/pulls/{pr_number}/commits".format(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
    )
    status, body, _ = gitea_api_request("GET", path)

    if status >= 300:
        raise ValueError(
            "failed to fetch PR commits: status={0}, body={1}".format(status, body[:500])
        )

    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError("PR commits API did not return a list")

    return data


def normalize_check_result(raw_result):
    result = raw_result if isinstance(raw_result, dict) else {}
    normalized = {}

    for field in REQUIRED_CHECK_FIELDS:
        normalized[field] = result.get(field)

    normalized["feature"] = str(normalized["feature"] or "")
    normalized["title_violations"] = normalized["title_violations"] or []
    normalized["commit_violations"] = normalized["commit_violations"] or []
    normalized["comment_violations"] = normalized["comment_violations"] or []
    normalized["has_violations"] = bool(normalized["has_violations"])
    normalized["comment"] = str(normalized["comment"] or "")

    for field in OPTIONAL_CHECK_FIELDS:
        normalized[field] = result.get(field)

    normalized["always_comment"] = bool(normalized.get("always_comment"))

    return normalized


def run_enabled_checks(pr_title, commits, diff_text):
    results = []
    for check in get_enabled_checks():
        raw_result = check.run(pr_title=pr_title, commits=commits, diff_text=diff_text)
        results.append(normalize_check_result(raw_result))
    return results


def aggregate_english_result(check_results):
    for result in check_results:
        if result.get("feature") == english_text_check.FEATURE_KEY:
            return result

    return {
        "title_violations": [],
        "commit_violations": [],
        "comment_violations": [],
        "has_violations": False,
        "comment": "",
    }


# Backward-compatible exports used by tests and existing integrations.
extract_non_ascii_comments = english_text_check.extract_non_ascii_comments
extract_invalid_pr_title = english_text_check.extract_invalid_pr_title
extract_invalid_commit_messages = english_text_check.extract_invalid_commit_messages


def lambda_handler(event, context):
    try:
        if not GITEA_BASE_URL:
            return response(500, {"ok": False, "error": "Missing env var GITEA_BASE_URL"})
        if not GITEA_TOKEN:
            return response(500, {"ok": False, "error": "Missing env var GITEA_TOKEN"})
        if not WEBHOOK_SECRET:
            return response(500, {"ok": False, "error": "Missing env var WEBHOOK_SECRET"})

        headers = event.get("headers") or {}
        lower_headers = normalize_headers(headers)

        raw_body, body_text = extract_request_body(event)

        if not verify_signature(raw_body, headers):
            return response(401, {"ok": False, "error": "bad signature"})

        event_name = lower_headers.get("x-gitea-event") or lower_headers.get("x-github-event")
        if event_name != "pull_request":
            return response(200, {"ok": True, "ignored": True, "reason": "unsupported event"})

        payload = json.loads(body_text)
        action = payload.get("action")

        if action not in ALLOWED_ACTIONS:
            return response(200, {"ok": True, "ignored": True, "reason": "unsupported action"})

        if not is_org_pr(payload, ORG_NAME):
            return response(200, {"ok": True, "ignored": True, "reason": "not org PR"})

        repo = payload.get("repository") or {}
        repo_owner = ((repo.get("owner") or {}).get("login")) or ""
        repo_name = repo.get("name") or ""

        pr = payload.get("pull_request") or {}
        pr_number = payload.get("number") or pr.get("number")
        sha = ((pr.get("head") or {}).get("sha")) or ""
        pr_html_url = pr.get("html_url") or ""
        pr_title = pr.get("title") or ""

        if not repo_owner or not repo_name or not pr_number or not sha:
            return response(400, {
                "ok": False,
                "error": "missing repository or PR fields",
            })

        pending_status, pending_body, _ = set_commit_status(
            repo_owner,
            repo_name,
            sha,
            "pending",
            "English text check is running",
            pr_html_url,
        )

        if pending_status >= 300:
            return response(502, {
                "ok": False,
                "error": "failed to set pending commit status",
                "gitea_status": pending_status,
                "gitea_body": pending_body[:2000],
            })

        diff_text = fetch_pr_diff(repo_owner, repo_name, int(pr_number))

        try:
            commits = fetch_pr_commits(repo_owner, repo_name, int(pr_number))
        except Exception as e:
            print("DEBUG commit check skipped:", str(e))
            commits = []

        check_results = run_enabled_checks(pr_title=pr_title, commits=commits, diff_text=diff_text)
        english_result = aggregate_english_result(check_results)

        title_violations = english_result["title_violations"]
        commit_violations = english_result["commit_violations"]
        comment_violations = english_result["comment_violations"]
        has_violations = any(bool(item.get("has_violations")) for item in check_results)

        comments_to_post = []
        for item in check_results:
            comment_text = str(item.get("comment") or "").strip()
            if not comment_text:
                continue
            if item.get("has_violations") or item.get("always_comment"):
                comments_to_post.append(comment_text)

        if comments_to_post:
            full_comment = "\n\n---\n\n".join(comments_to_post)
            comment_status, comment_body, _ = post_pr_comment(
                repo_owner,
                repo_name,
                int(pr_number),
                full_comment,
            )

            if comment_status >= 300:
                return response(502, {
                    "ok": False,
                    "error": "failed to post comment",
                    "gitea_status": comment_status,
                    "gitea_body": comment_body[:2000],
                })

        if has_violations:
            status_state = "failure"
            status_description = "One or more PR checks failed"
        else:
            status_state = "success"
            status_description = "All PR checks passed"

        final_status, final_body, _ = set_commit_status(
            repo_owner,
            repo_name,
            sha,
            status_state,
            status_description,
            pr_html_url,
        )

        if final_status >= 300:
            return response(502, {
                "ok": False,
                "error": "failed to set commit status",
                "gitea_status": final_status,
                "gitea_body": final_body[:2000],
            })

        return response(200, {
            "ok": True,
            "repository": "{0}/{1}".format(repo_owner, repo_name),
            "pr_number": pr_number,
            "violations": len(title_violations) + len(commit_violations) + len(comment_violations),
            "title_violations": len(title_violations),
            "commit_violations": len(commit_violations),
            "comment_violations": len(comment_violations),
            "status_context": STATUS_CONTEXT,
            "status_state": status_state,
        })

    except Exception as e:
        return response(500, {
            "ok": False,
            "error": type(e).__name__,
            "details": str(e),
        })
