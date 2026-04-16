import json
import os

FEATURE_KEY = "commit_message_quality"

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
MAX_REVIEWED_COMMITS = int(os.getenv("MAX_REVIEWED_COMMITS", "20"))

SYSTEM_PROMPT = """
You are a strict Git commit message reviewer.

Evaluate a git commit message against these 7 rules:

1. Separate subject from body with a blank line
2. Limit the subject line to 50 characters
3. Capitalize the subject line
4. Do not end the subject line with a period
5. Use the imperative mood in the subject line
6. Wrap the body at 72 characters
7. Use the body to explain what and why vs. how

Return ONLY valid JSON in this exact shape:

{
  "overall_pass": true,
  "score": 0,
  "subject": "",
  "body_present": true,
  "checks": [
    {
      "rule": "Separate subject from body with a blank line",
      "passed": true,
      "details": ""
    },
    {
      "rule": "Limit the subject line to 50 characters",
      "passed": true,
      "details": ""
    },
    {
      "rule": "Capitalize the subject line",
      "passed": true,
      "details": ""
    },
    {
      "rule": "Do not end the subject line with a period",
      "passed": true,
      "details": ""
    },
    {
      "rule": "Use the imperative mood in the subject line",
      "passed": true,
      "details": ""
    },
    {
      "rule": "Wrap the body at 72 characters",
      "passed": true,
      "details": ""
    },
    {
      "rule": "Use the body to explain what and why vs. how",
      "passed": true,
      "details": ""
    }
  ],
  "suggested_commit_message": "",
  "summary": ""
}

Scoring:
- score is from 0 to 7
- overall_pass is true only if at least 6/7 pass and rule 5 is passed

Notes:
- If there is no body, rule 6 and 7 may fail if context is needed.
- For imperative mood, judge linguistically. Examples of good forms:
  "Add", "Fix", "Refactor", "Update", "Remove"
- Keep details concise and actionable.
- suggested_commit_message should be improved and follow the rules.
""".strip()


def _is_enabled():
    if (os.getenv("COMMIT_MESSAGE_AI_CHECK_ENABLED", "true").strip().lower()
            not in {"1", "true", "yes", "on"}):
        return False

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    return bool(api_key)


def _review_commit_message(client, commit_message):
    response = client.responses.create(
        model=DEFAULT_MODEL,
        input=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": "Review this git commit message:\n\n{0}".format(commit_message),
            },
        ],
    )

    text = response.output_text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "overall_pass": False,
            "score": 0,
            "summary": "Model did not return valid JSON",
            "raw_response": text[:2000],
        }


def _build_comment(violations):
    lines = ["❌ Commit message quality check failed\n"]
    lines.append(
        "The following commits do not match the team commit-message rules "
        "(imperative subject, length, body formatting):\n"
    )

    for item in violations[:20]:
        sha_short = item.get("sha", "")[:8]
        lines.append("- **{0}** `{1}`".format(item.get("subject", "(no subject)"), sha_short))

        for detail in item.get("failed_rules", [])[:4]:
            lines.append("  - {0}".format(detail))

        suggestion = item.get("suggested_commit_message", "").strip()
        if suggestion:
            lines.append("  - Suggested:")
            lines.append("    ```text")
            lines.append("    {0}".format(suggestion.replace("\n", "\n    ")))
            lines.append("    ```")

    lines.append("\nPlease update commit messages (or squash/reword) before merging.")
    return "\n".join(lines)


def run(pr_title, commits, diff_text):
    del pr_title, diff_text

    if not _is_enabled() or not commits:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "",
        }

    try:
        from openai import OpenAI
    except Exception:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "",
        }

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    violations = []

    for commit_item in commits[:MAX_REVIEWED_COMMITS]:
        commit = commit_item.get("commit") or {}
        message = commit.get("message") or ""
        if not message.strip():
            continue

        review = _review_commit_message(client, message)
        if review.get("overall_pass"):
            continue

        checks = review.get("checks") or []
        failed_rules = []
        for rule_item in checks:
            if rule_item.get("passed"):
                continue
            rule = str(rule_item.get("rule") or "Rule")
            details = str(rule_item.get("details") or "").strip()
            failed_rules.append("{0}: {1}".format(rule, details) if details else rule)

        violations.append({
            "type": "commit_message_quality",
            "sha": commit_item.get("sha") or "",
            "subject": (message.splitlines()[0] or "")[:300],
            "score": review.get("score", 0),
            "summary": str(review.get("summary") or "").strip(),
            "failed_rules": failed_rules,
            "suggested_commit_message": str(review.get("suggested_commit_message") or "").strip(),
        })

    return {
        "feature": FEATURE_KEY,
        "title_violations": [],
        "commit_violations": violations,
        "comment_violations": [],
        "has_violations": bool(violations),
        "comment": _build_comment(violations) if violations else "",
    }
