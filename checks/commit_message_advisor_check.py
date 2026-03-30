import json
import os
import re
import urllib.error
import urllib.request


FEATURE_KEY = "commit_message_advisor"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
ADVISOR_MODEL = os.getenv("COMMIT_MESSAGE_ADVISOR_MODEL", "gpt-4o-mini")
MAX_COMMITS = int(os.getenv("COMMIT_MESSAGE_ADVISOR_MAX_COMMITS", "20"))
JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

def _extract_commit_subjects(commits):
    result = []
    seen = set()
    for item in commits[:MAX_COMMITS]:
        message = ((item.get("commit") or {}).get("message")) or ""
        if not message.strip():
            continue

        lines = message.splitlines()
        subject = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        normalized_subject = subject.strip().lower()
        if normalized_subject in seen:
            continue
        seen.add(normalized_subject)

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


def _safe_parse_analysis_payload(text):
    parsed = _safe_json_loads(text)
    if isinstance(parsed, dict) and isinstance(parsed.get("analysis"), list):
        return parsed

    # Some models return markdown-wrapped or prefixed text. Try extracting
    # the first JSON object from the output.
    match = JSON_BLOCK_RE.search(text or "")
    if match:
        parsed = _safe_json_loads(match.group(0))
        if isinstance(parsed, dict) and isinstance(parsed.get("analysis"), list):
            return parsed

    return {}


def _build_advisory_comment(analysis_items):
    if not analysis_items:
        return ""

    lines = []
    lines.append("💡 Commit message recommendations (non-blocking)\n")

    for item in analysis_items:
        subject = item.get("subject") or "(empty subject)"
        verdict = (item.get("verdict") or "").strip().lower()
        suggestion = (item.get("suggested_subject") or "").strip()
        reason = (item.get("reason") or "").strip()

        lines.append("")
        if verdict == "ok":
            lines.append("- **{0}** → ✅ OK".format(subject))
            continue

        if suggestion:
            lines.append("- **{0}** → ✍️ `{1}`".format(subject, suggestion))
        else:
            lines.append("- **{0}** → ✍️ Improve commit message".format(subject))

        if reason:
            lines.append("  - {0}".format(reason))

    return "\n".join(lines)


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
    advisor_error = ""
    if not OPENAI_API_KEY:
        advisor_error = "⚠️ Commit advisor error: OPENAI_API_KEY is not configured."

    if OPENAI_API_KEY:
        payload = {
            "model": ADVISOR_MODEL,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are a Git commit message reviewer. "
                        "For each commit message return ONLY compact JSON with key "
                        "'analysis' as list of objects. "
                        "Object schema: subject (string), verdict ('ok'|'rewrite'), "
                        "suggested_subject (string, empty when verdict='ok'), "
                        "reason (string <= 120 chars). "
                        "Use the 7 classic rules (English, imperative mood, <=50 chars, "
                        "etc). If message is good, verdict must be 'ok'."
                    ),
                },
                {
                    "role": "user",
                    "content": _build_input_text(pr_title, items),
                },
            ],
            "max_output_tokens": 700,
        }

        status, body = _responses_api_request(payload)
        if status < 300:
            api_json = _safe_json_loads(body)
            content_text = _parse_response_text(api_json)
            parsed_content = _safe_parse_analysis_payload(content_text)
            candidate = (
                parsed_content.get("analysis")
                if isinstance(parsed_content, dict)
                else []
            )
            if isinstance(candidate, list):
                analysis_items = candidate
            else:
                advisor_error = "⚠️ Commit advisor error: model returned invalid JSON format."
        else:
            advisor_error = "⚠️ Commit advisor error: request failed with status {0}.".format(status)

    comment = _build_advisory_comment(analysis_items)
    if advisor_error:
        comment = (comment + "\n\n" if comment else "") + advisor_error

    return {
        "feature": FEATURE_KEY,
        "title_violations": [],
        "commit_violations": analysis_items,
        "comment_violations": [],
        "has_violations": bool(analysis_items or advisor_error),
        "comment": comment,
        "is_advisory": True,
    }
