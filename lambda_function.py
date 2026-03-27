import os
import json
import hmac
import hashlib
import base64
import re
import urllib.request
import urllib.error
import unicodedata


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

EXCLUDED_FILES = {".json", ".p7s", ".cjs", ".po", ".license", ".xml", ".md", ".resx"}

COMMENT_REGEX = re.compile(r"(?://|#|<!--|/\*|\*).+")
QUOTED_TEXT_REGEX = re.compile(r'(".*?"|\'.*?\')')

ALLOWED_SYMBOLS = {'↓', '↑', '←', '→', '⌘', '⌥', '©', '•', '—', '─'}


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


def is_excluded_file(file_path):
    return file_path.endswith(tuple(EXCLUDED_FILES))


def deduplicate_mixed_violations(violations):
    seen = set()
    result = []

    for item in violations:
        key = (
            item.get("type", ""),
            item.get("file", ""),
            item.get("content", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)

    return result


def is_allowed_char(ch):
    if ch in ALLOWED_SYMBOLS:
        return True

    code = ord(ch)

    if 0x00 <= code <= 0x7F:
        return True

    try:
        name = unicodedata.name(ch)
    except ValueError:
        return False

    category = unicodedata.category(ch)

    if "LATIN" in name:
        return True

    if category.startswith("P") or category.startswith("Z"):
        return True

    return False


def contains_invalid_chars(text):
    if not text:
        return False

    for ch in text:
        if not is_allowed_char(ch):
            return True

    return False


def has_invalid_non_ascii_outside_quotes(text):
    if not text:
        return False

    cleaned = QUOTED_TEXT_REGEX.sub("", text)
    return contains_invalid_chars(cleaned)


def extract_non_ascii_comments(diff_text):
    violations = []
    current_file = None

    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\r\n")

        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue

        if line.startswith("+++") or line.startswith("+++ /dev/null"):
            continue

        if not line.startswith("+") or line.startswith("+++"):
            continue

        if not current_file or is_excluded_file(current_file):
            continue

        added_text = line[1:].strip()

        if not added_text:
            continue

        if not COMMENT_REGEX.search(added_text):
            continue

        if contains_invalid_chars(added_text):
            violations.append({
                "type": "comment",
                "file": current_file,
                "content": added_text[:300],
            })

    return deduplicate_mixed_violations(violations)


def extract_invalid_pr_title(pr_title):
    if has_invalid_non_ascii_outside_quotes(pr_title):
        return [{
            "type": "pr_title",
            "content": pr_title[:300],
        }]
    return []


def extract_invalid_commit_messages(commits):
    violations = []

    for commit_item in commits:
        try:
            message = ((commit_item.get("commit") or {}).get("message")) or ""
        except Exception:
            message = ""

        if not message:
            continue

        if has_invalid_non_ascii_outside_quotes(message):
            violations.append({
                "type": "commit_message",
                "content": message.split("\n")[0][:300],
            })

    return deduplicate_mixed_violations(violations)


def build_comment(title_violations, commit_violations, comment_violations):
    lines = []
    lines.append("❌ English text check failed\n")

    if title_violations:
        lines.append("Non-English characters were found in the PR title (outside quotes):\n")
        for item in title_violations:
            lines.append("```text\n{0}\n```".format(item["content"]))

    if commit_violations:
        if title_violations:
            lines.append("")
        lines.append("Non-English characters were found in commit messages (outside quotes):\n")
        for item in commit_violations[:20]:
            lines.append("- ```text\n  {0}\n  ```".format(item["content"]))

    if comment_violations:
        if title_violations or commit_violations:
            lines.append("")
        lines.append("Non-English characters were found in code comments:\n")
        for item in comment_violations[:20]:
            lines.append(
                "- **{0}**\n"
                "  ```text\n"
                "  {1}\n"
                "  ```".format(item["file"], item["content"])
            )

    lines.append("\nPlease replace these characters with English-only text before merging.")
    return "\n".join(lines)


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
        comment_violations = extract_non_ascii_comments(diff_text)
        title_violations = extract_invalid_pr_title(pr_title)

        try:
            commits = fetch_pr_commits(repo_owner, repo_name, int(pr_number))
            commit_violations = extract_invalid_commit_messages(commits)
        except Exception as e:
            print("DEBUG commit check skipped:", str(e))
            commit_violations = []

        has_violations = bool(
            title_violations or commit_violations or comment_violations
        )

        if has_violations:
            comment = build_comment(
                title_violations,
                commit_violations,
                comment_violations,
            )

            comment_status, comment_body, _ = post_pr_comment(
                repo_owner,
                repo_name,
                int(pr_number),
                comment,
            )

            if comment_status >= 300:
                return response(502, {
                    "ok": False,
                    "error": "failed to post comment",
                    "gitea_status": comment_status,
                    "gitea_body": comment_body[:2000],
                })

            status_state = "failure"
            status_description = "Non-English characters found"
        else:
            status_state = "success"
            status_description = "English text check passed"

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
