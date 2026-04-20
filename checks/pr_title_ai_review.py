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

IMPERATIVE_HINTS = {"add", "fix", "update", "remove", "refactor", "improve", "rename", "bump"}
GENERIC_TITLES = {"dockerfile", "changes", "update", "fix", "test", "readme"}


def _build_ok_comment(title, summary):
    lines = [
        "✅ PR title review: all good.",
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
        "❌ PR title review found issues.",
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


def _build_result(pr_title, checks, overall_pass, suggested_title, summary):
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
        "title_violations": [] if overall_pass else failed_rules,
        "commit_violations": [],
        "comment_violations": [],
        "has_violations": not overall_pass,
        "always_comment": True,
        "comment": _build_ok_comment(pr_title, summary)
        if overall_pass
        else _build_fail_comment(pr_title, checks, suggested_title, summary),
    }


def _rule(name, passed, details):
    return {"rule": name, "passed": bool(passed), "details": details}


def _local_review(pr_title):
    title = (pr_title or "").strip()
    first_word = title.split()[0].lower() if title.split() else ""

    checks = [
        _rule("Keep title concise", len(title) <= 72, "Use up to 72 characters."),
        _rule("Start with a capital letter", title[:1].isupper(), "Capitalize first letter."),
        _rule("Do not end with punctuation", not title.endswith((".", "!", "?")), "Remove ending punctuation."),
        _rule(
            "Prefer imperative style",
            first_word in IMPERATIVE_HINTS,
            "Start with an imperative verb (Add/Fix/Update/Remove/Refactor).",
        ),
        _rule(
            "Be specific and clear",
            len(title.split()) >= 2 and title.lower() not in GENERIC_TITLES,
            "Avoid generic one-word titles, add context.",
        ),
    ]

    passed = sum(1 for item in checks if item["passed"])
    overall_pass = passed >= 4 and checks[3]["passed"]
    suggested_title = "Update Dockerfile configuration" if title.lower() == "dockerfile" else ""
    summary = "Used local fallback review because OpenAI response was unavailable."

    return _build_result(pr_title, checks, overall_pass, suggested_title, summary)


def run(pr_title, commits, diff_text):
    del commits, diff_text

    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key or OpenAI is None:
        return _local_review(pr_title)

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

        checks = data.get("checks") if isinstance(data, dict) else []
        checks = checks if isinstance(checks, list) else []
        overall_pass = bool(data.get("overall_pass")) if isinstance(data, dict) else False
        suggested_title = str(data.get("suggested_title") or "").strip() if isinstance(data, dict) else ""
        summary = str(data.get("summary") or "").strip() if isinstance(data, dict) else ""

        if not checks:
            return _local_review(pr_title)

        return _build_result(pr_title, checks, overall_pass, suggested_title, summary)
    except Exception:
        return _local_review(pr_title)
