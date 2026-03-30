import json
import os
import urllib.error
import urllib.request


FEATURE_KEY = "commit_message_advisor"

ADVISOR_ENABLED = os.getenv("COMMIT_MESSAGE_ADVISOR_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
ADVISOR_MODEL = os.getenv("COMMIT_MESSAGE_ADVISOR_MODEL", "gpt-4o-mini")
MAX_COMMITS = int(os.getenv("COMMIT_MESSAGE_ADVISOR_MAX_COMMITS", "20"))


def _extract_commit_subjects(commits):
    result = []
    for item in commits[:MAX_COMMITS]:
        message = ((item.get("commit") or {}).get("message")) or ""
        if not message.strip():
            continue

        lines = message.splitlines()
        subject = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        result.append({"subject": subject, "body": body})
    return result


def _responses_api_request(payload):
    url = OPENAI_BASE_URL + "/responses"
    body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url=url,
        method="POST",
        data=body,
        headers={
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, raw
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        return error.code, raw
    except Exception as error:
        return 599, str(error)


def _build_input_text(pr_title, commits):
    chunks = ["PR title: {0}".format(pr_title or "")]
    for idx, item in enumerate(commits, start=1):
        chunks.append("Commit #{0} subject: {1}".format(idx, item["subject"]))
        if item["body"]:
            chunks.append("Commit #{0} body:\n{1}".format(idx, item["body"]))
    return "\n\n".join(chunks)


def _parse_response_text(api_json):
    output = api_json.get("output") or []
    for output_item in output:
        for content_item in output_item.get("content") or []:
            if content_item.get("type") == "output_text":
                return content_item.get("text") or ""
    return ""


def _safe_json_loads(text):
    try:
        return json.loads(text)
    except Exception:
        return {}


def _build_advisory_comment(analysis_items):
    if not analysis_items:
        return ""

    lines = []
    lines.append("💡 Commit message recommendations (non-blocking)\n")
    lines.append(
        "These suggestions follow the 7 classic commit message rules "
        "(subject/body split, <=50 chars, imperative mood, etc.)."
    )

    for item in analysis_items:
        subject = item.get("subject") or "(empty subject)"
        score = item.get("score")
        summary = item.get("summary") or ""
        suggestions = item.get("suggestions") or []

        lines.append("")
        if isinstance(score, int):
            lines.append("- **{0}** — score: {1}/100".format(subject, score))
        else:
            lines.append("- **{0}**".format(subject))

        if summary:
            lines.append("  - {0}".format(summary))

        for suggestion in suggestions[:5]:
            lines.append("  - {0}".format(str(suggestion)))

    return "\n".join(lines)


def run(pr_title, commits, diff_text):
    del diff_text

    if not ADVISOR_ENABLED:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "",
            "is_advisory": True,
        }

    if not OPENAI_API_KEY:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": (
                "⚠️ Commit message advisor is enabled but OPENAI_API_KEY is missing."
            ),
            "is_advisory": True,
        }

    items = _extract_commit_subjects(commits)
    if not items:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "",
            "is_advisory": True,
        }

    payload = {
        "model": ADVISOR_MODEL,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a Git commit message reviewer. "
                    "Evaluate each commit message against the 7 rules: "
                    "blank line between subject and body, <=50 char subject, "
                    "capitalize subject, no trailing period in subject, "
                    "imperative mood, body wrapped around 72 chars, "
                    "body explains what/why more than how. "
                    "Return strict JSON with key 'analysis' as a list of items. "
                    "Each item must have: subject (string), score (0-100 integer), "
                    "summary (string), suggestions (array of short strings)."
                ),
            },
            {
                "role": "user",
                "content": _build_input_text(pr_title, items),
            },
        ],
        "max_output_tokens": 900,
    }

    status, body = _responses_api_request(payload)
    if status >= 300:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": (
                "⚠️ Commit message advisor request failed: status={0}. "
                "Check model, token, and endpoint settings."
            ).format(status),
            "is_advisory": True,
        }

    api_json = _safe_json_loads(body)
    content_text = _parse_response_text(api_json)
    parsed_content = _safe_json_loads(content_text)
    analysis_items = parsed_content.get("analysis") if isinstance(parsed_content, dict) else []

    if not isinstance(analysis_items, list):
        analysis_items = []

    comment = _build_advisory_comment(analysis_items)

    return {
        "feature": FEATURE_KEY,
        "title_violations": [],
        "commit_violations": analysis_items,
        "comment_violations": [],
        "has_violations": bool(analysis_items),
        "comment": comment,
        "is_advisory": True,
    }
