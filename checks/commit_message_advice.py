import json
import os
import urllib.error
import urllib.request


FEATURE_KEY = "commit_message_advice"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
OPENAI_API_URL = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/responses")


def extract_commit_subjects(commits):
    subjects = []

    for commit_item in commits:
        message = ((commit_item.get("commit") or {}).get("message")) or ""
        if not message:
            continue

        first_line = message.splitlines()[0].strip()
        if first_line:
            subjects.append(first_line)

    return subjects


def build_prompt(pr_title, commit_subjects):
    guidelines = [
        "1. Separate subject from body with a blank line",
        "2. Keep the subject line within 50 characters if possible (up to 72 is acceptable)",
        "3. Capitalize the subject line",
        "4. Do not end the subject line with a period",
        "5. Use the imperative mood in the subject line",
        "6. Wrap body lines at around 72 characters",
        "7. Explain what and why, not how",
    ]

    commit_list = "\n".join("- " + item for item in commit_subjects) or "- (no commits found)"

    return (
        "You are a friendly reviewer helping with commit message quality.\n"
        "Analyze the PR title and commit subjects using the conventional commit writing recommendations below.\n"
        "These are recommendations only; never suggest blocking the PR.\n"
        "Respond in English, concise and friendly.\n"
        "If the messages are already good, explicitly say that no changes are required.\n\n"
        "Output JSON with this schema:\n"
        "{\n"
        '  "overall_assessment": "short sentence",\n'
        '  "suggestions": ["1-3 concise suggestions, or empty if no changes required"]\n'
        "}\n\n"
        "Rules to evaluate:\n{rules}\n\n"
        "PR title:\n{title}\n\n"
        "Commit subjects:\n{commits}\n"
    ).format(rules="\n".join(guidelines), title=pr_title or "(empty)", commits=commit_list)


def call_openai(prompt):
    payload = {
        "model": OPENAI_MODEL,
        "input": prompt,
        "text": {"format": {"type": "json_object"}},
    }

    req = urllib.request.Request(
        url=OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8", errors="replace")

    data = json.loads(body)
    output_text = data.get("output_text")
    if output_text:
        return output_text

    for item in data.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if text:
                return text

    raise ValueError("OpenAI response did not include text output")


def parse_response(text):
    parsed = json.loads(text)
    overall = str(parsed.get("overall_assessment") or "").strip()
    suggestions = parsed.get("suggestions") or []
    if not isinstance(suggestions, list):
        suggestions = []

    cleaned_suggestions = []
    for item in suggestions[:3]:
        suggestion = str(item).strip()
        if suggestion:
            cleaned_suggestions.append(suggestion)

    return overall, cleaned_suggestions


def build_comment(overall, suggestions):
    lines = ["💡 Commit/PR title writing tips"]
    lines.append("")
    lines.append("**Overall assessment:** {0}".format(overall or "Looks good."))

    if suggestions:
        lines.append("")
        lines.append("**Suggestions:**")
        for idx, item in enumerate(suggestions, start=1):
            lines.append("{0}. {1}".format(idx, item))
    else:
        lines.append("")
        lines.append("No changes are required.")

    return "\n".join(lines)


def run(pr_title, commits, diff_text):
    _ = diff_text
    commit_subjects = extract_commit_subjects(commits)

    if not OPENAI_API_KEY:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "",
        }

    try:
        prompt = build_prompt(pr_title, commit_subjects)
        raw_text = call_openai(prompt)
        overall, suggestions = parse_response(raw_text)
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": bool(suggestions),
            "comment": build_comment(overall, suggestions),
        }
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "",
        }
