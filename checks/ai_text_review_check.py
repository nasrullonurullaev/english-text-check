import json
import os


FEATURE_KEY = "ai_text_review"
AI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

SYSTEM_PROMPT = """
You are a strict reviewer for pull request text quality.

Evaluate a commit or pull-request title text against these 8 rules:

1. Separate subject from body with a blank line (for commit messages)
2. Limit the subject line to 50 characters
3. Capitalize the subject line
4. Do not end the subject line with a period
5. Use the imperative mood in the subject line
6. Wrap the body at 72 characters (for commit messages with body)
7. Use the body to explain what and why vs. how
8. If text includes bracketed platform tags like [iOS], [Android], [Web], treat them as valid context markers, not a style violation

Return ONLY valid JSON in this exact shape:
{
  "overall_pass": true,
  "score": 0,
  "subject": "",
  "body_present": true,
  "checks": [],
  "suggested_commit_message": "",
  "summary": ""
}
""".strip()


def _review_text(client, item_type, text):
    user_prompt = (
        "Review this {0}. Return only JSON.\n\n{1}".format(item_type, text)
    )

    response = client.responses.create(
        model=AI_MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw_text = (response.output_text or "").strip()
    if not raw_text:
        raise ValueError("OpenAI returned an empty response")

    result = json.loads(raw_text)
    if not isinstance(result, dict):
        raise ValueError("OpenAI response JSON must be an object")

    return result


def _build_comment(pr_title_result, commit_results):
    lines = [
        "### 🤖 PR title & commit message review",
        "ℹ️ Review is based on the 7 classic commit message rules: https://chris.beams.io/git-commit#seven-rules",
    ]

    if pr_title_result:
        if pr_title_result.get("overall_pass"):
            lines.append("✅ PR title: looks good.")
        else:
            lines.append("💡 PR title: improvement suggestion.")
            lines.append("- Advice: {0}".format(pr_title_result.get("summary") or "No summary"))
            suggestion = pr_title_result.get("suggested_commit_message") or ""
            if suggestion:
                lines.append("- Suggested title: `{0}`".format(suggestion.split("\n")[0][:120]))

    if commit_results:
        failed = [x for x in commit_results if not x.get("overall_pass")]
        if not failed:
            lines.append("✅ Commit messages: all reviewed commits look good.")
        else:
            lines.append("💡 Commit messages: {0} suggestion(s).".format(len(failed)))
            for item in failed[:5]:
                lines.append("- `{0}`".format(item.get("subject") or "(no subject)"))
                lines.append("  - Advice: {0}".format(item.get("summary") or "Needs improvement"))
                suggestion = item.get("suggested_commit_message") or ""
                if suggestion:
                    lines.append("  - Example: `{0}`".format(suggestion.split("\n")[0][:120]))

    if pr_title_result and pr_title_result.get("overall_pass") and not commit_results:
        lines.append("✅ Everything is OK.")

    return "\n".join(lines)


def run(pr_title, commits, diff_text):
    del diff_text

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "⚠️ AI text review skipped: OPENAI_API_KEY is not configured.",
            "should_comment": True,
        }

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        pr_title_result = _review_text(client, "pull request title", pr_title or "")

        commit_results = []
        for commit_item in commits[:20]:
            message = ((commit_item.get("commit") or {}).get("message")) or ""
            if not message:
                continue
            reviewed = _review_text(client, "git commit message", message)
            commit_results.append(reviewed)

        title_violations = []
        if not pr_title_result.get("overall_pass"):
            title_violations.append({
                "type": "ai_pr_title",
                "content": (pr_title_result.get("summary") or "PR title should be improved")[:300],
            })

        commit_violations = []
        for item in commit_results:
            if not item.get("overall_pass"):
                commit_violations.append({
                    "type": "ai_commit_message",
                    "content": (item.get("summary") or "Commit message should be improved")[:300],
                })

        # AI review is advisory and must not fail the overall commit status.
        has_violations = False

        return {
            "feature": FEATURE_KEY,
            "title_violations": title_violations,
            "commit_violations": commit_violations,
            "comment_violations": [],
            "has_violations": has_violations,
            "comment": _build_comment(pr_title_result, commit_results),
            "should_comment": True,
        }
    except Exception as e:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "⚠️ AI text review skipped due to error: {0}".format(str(e)[:400]),
            "should_comment": True,
        }
