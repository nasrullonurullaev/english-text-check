import json
import os

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


FEATURE_KEY = "pr_title_ai_review"
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SYSTEM_PROMPT = """
You are a strict pull request title reviewer.

Evaluate a PR title against these 5 rules:
1. Keep title concise (ideally <= 72 chars)
2. Start with a capital letter
3. Do not end with punctuation like '.' or '!'
4. Prefer imperative style (e.g. Add, Fix, Update, Remove, Refactor)
5. Be specific and clear

Return ONLY valid JSON in this exact shape:
{
  "overall_pass": true,
  "score": 0,
  "checks": [
    {"rule": "Keep title concise", "passed": true, "details": ""},
    {"rule": "Start with a capital letter", "passed": true, "details": ""},
    {"rule": "Do not end with punctuation", "passed": true, "details": ""},
    {"rule": "Prefer imperative style", "passed": true, "details": ""},
    {"rule": "Be specific and clear", "passed": true, "details": ""}
  ],
  "suggested_title": "",
  "summary": ""
}

Rules:
- score is from 0 to 5
- overall_pass is true only if score >= 4 and imperative style is passed
- details should be short and actionable
""".strip()


def _is_enabled():
    return os.getenv("ENABLE_PR_TITLE_AI_CHECK", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _build_ok_comment(title, summary):
    lines = [
        "✅ PR title AI review: all good.",
        "",
        "Checked title:",
        "```text",
        title[:300],
        "```",
    ]
    if summary:
        lines.extend(["", "Notes: {0}".format(summary.strip())])
    return "\n".join(lines)


def _build_fail_comment(title, checks, suggested_title, summary):
    lines = [
        "❌ PR title AI review found issues.",
        "",
        "Current title:",
        "```text",
        title[:300],
        "```",
        "",
        "Advice:",
    ]

    for item in checks:
        if item.get("passed"):
            continue
        rule = (item.get("rule") or "Rule").strip()
        details = (item.get("details") or "Needs improvement").strip()
        lines.append("- **{0}**: {1}".format(rule, details))

    if suggested_title:
        lines.extend([
            "",
            "Example title:",
            "```text",
            suggested_title[:300],
            "```",
        ])

    if summary:
        lines.extend(["", "Summary: {0}".format(summary.strip())])

    return "\n".join(lines)


def _fallback_result(pr_title, reason):
    return {
        "feature": FEATURE_KEY,
        "title_violations": [],
        "commit_violations": [],
        "comment_violations": [],
        "has_violations": False,
        "always_comment": True,
        "comment": "⚠️ PR title AI review skipped: {0}".format(reason),
    }


def run(pr_title, commits, diff_text):
    del commits, diff_text

    if not _is_enabled():
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "always_comment": False,
            "comment": "",
        }

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _fallback_result(pr_title, "missing OPENAI_API_KEY")

    if OpenAI is None:
        return _fallback_result(pr_title, "python package 'openai' is not installed")

    try:
        client = OpenAI(api_key=api_key)
        resp = client.responses.create(
            model=DEFAULT_MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Review this PR title:\n\n{0}".format(pr_title),
                },
            ],
        )
        text = (resp.output_text or "").strip()
        data = json.loads(text)
    except Exception as e:
        return _fallback_result(pr_title, "model error: {0}".format(str(e)))

    checks = data.get("checks") if isinstance(data, dict) else []
    checks = checks if isinstance(checks, list) else []
    overall_pass = bool(data.get("overall_pass")) if isinstance(data, dict) else False
    suggested_title = ""
    summary = ""

    if isinstance(data, dict):
        suggested_title = str(data.get("suggested_title") or "").strip()
        summary = str(data.get("summary") or "").strip()

    if overall_pass:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "always_comment": True,
            "comment": _build_ok_comment(pr_title, summary),
        }

    failed_rules = [
        {
            "type": "pr_title_ai_rule",
            "content": str(item.get("rule") or "").strip()[:300],
        }
        for item in checks
        if not item.get("passed")
    ]

    return {
        "feature": FEATURE_KEY,
        "title_violations": failed_rules,
        "commit_violations": [],
        "comment_violations": [],
        "has_violations": True,
        "always_comment": True,
        "comment": _build_fail_comment(pr_title, checks, suggested_title, summary),
    }
