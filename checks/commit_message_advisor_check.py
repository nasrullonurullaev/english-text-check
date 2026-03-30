import json
import os
import urllib.error
import urllib.request


FEATURE_KEY = "commit_message_advisor"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
ADVISOR_MODEL = os.getenv("COMMIT_MESSAGE_ADVISOR_MODEL", "gpt-4o-mini")
MAX_COMMITS = int(os.getenv("COMMIT_MESSAGE_ADVISOR_MAX_COMMITS", "20"))

COMMON_NON_IMPERATIVE_STARTS = (
    "added",
    "fixed",
    "changed",
    "updated",
    "removed",
    "refactored",
)


def _extract_commit_subjects(commits):
    result = []
    for item in commits[:MAX_COMMITS]:
        message = ((item.get("commit") or {}).get("message")) or ""
        if not message.strip():
            continue

        lines = message.splitlines()
        subject = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        result.append(
            {
                "subject": subject,
                "body": body,
                "raw_message": message,
            }
        )
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


def _heuristic_analysis(commits):
    analysis = []

    for item in commits:
        subject = item["subject"]
        body = item["body"]
        suggestions = []

        if len(subject) > 50:
            suggestions.append("Keep the subject line at 50 characters or less.")

        if subject and not subject[0].isupper():
            suggestions.append("Capitalize the first letter in the subject line.")

        if subject.endswith("."):
            suggestions.append("Do not end the subject line with a period.")

        lowered = subject.lower().strip()
        if lowered.startswith(COMMON_NON_IMPERATIVE_STARTS):
            suggestions.append(
                "Prefer imperative mood in subject (e.g. 'Fix', 'Add', 'Update')."
            )

        if body and "\n\n" not in item.get("raw_message", ""):
            suggestions.append("Separate subject and body with a blank line.")

        if body:
            long_lines = [line for line in body.splitlines() if len(line) > 72]
            if long_lines:
                suggestions.append("Wrap body lines at about 72 characters.")

        if not body:
            suggestions.append(
                "Add a short body explaining what changed and why (non-blocking tip)."
            )

        summary = (
            "Looks good."
            if not suggestions
            else "Can be improved to better match commit message conventions."
        )
        score = max(0, 100 - len(suggestions) * 15)
        analysis.append(
            {
                "subject": subject,
                "score": score,
                "summary": summary,
                "suggestions": suggestions,
            }
        )

    return analysis


def run(pr_title, commits, diff_text):
    del diff_text

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

    analysis_items = []
    if OPENAI_API_KEY:
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
        if status < 300:
            api_json = _safe_json_loads(body)
            content_text = _parse_response_text(api_json)
            parsed_content = _safe_json_loads(content_text)
            candidate = (
                parsed_content.get("analysis")
                if isinstance(parsed_content, dict)
                else []
            )
            if isinstance(candidate, list):
                analysis_items = candidate

    if not analysis_items:
        analysis_items = _heuristic_analysis(items)

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
