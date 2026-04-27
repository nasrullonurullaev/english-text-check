import os
import importlib


FEATURE_KEY = "ai_text_review"
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-7-sonnet-latest")
ANTHROPIC_AVAILABLE = importlib.util.find_spec("anthropic") is not None

REVIEW_PROMPT_TEMPLATE = """
Read CLAUDE.md from the repository root to understand the repository context (tech stack, project structure, review focus, coding standards).
Then review this pull request following ALL instructions below precisely.

**Environment**: Gitea Actions (not GitHub), standard git operations, some GitHub Actions features may differ

## Review Workflow

**Context**: Read README.md and CLAUDE.md for project architecture and coding standards before reviewing.

### 1. Gather context

- Use the PR diff already available in context as the source of truth for all output sections
- Only run `git diff origin/<base_branch>...HEAD` if the available diff appears to cover only the latest commit (e.g., previous review references issues absent from the current context diff)
- Search PR comments for one containing `Claude Code Review` — this is the previous review

### 2. Build the review

- **If previous review found**: for each issue check if it is still present in the full PR diff
  - Fixed → replace its `<details>` block with a ⚪️ Fixed entry (preserving original severity)
  - Not fixed → keep it as-is
- Add any new issues found in the diff not already in the previous review
- PR Summary and Positive Observations reflect the full PR, not just the latest commit

### 2.1 Validate PR Title and Commit Messages

Evaluate PR title and commit messages using these rules:

1. Separate subject from body with a blank line (for commit messages)
2. Limit the subject line to 50 characters
3. Capitalize the subject line
4. Do not end the subject line with a period
5. Use the imperative mood in the subject line
6. Wrap the body at 72 characters (for commit messages with body)
7. Use the body to explain what and why vs. how
8. Allow bracketed platform tags like [iOS], [Android], [Web]

- Report violations in **🎨 Style** section
- Treat violations as:
  - 🟡 Medium → if it affects readability/standards consistency
  - 🔵 Low → minor formatting issues

### 3. Verdict Logic

**Determine [VERDICT] FIRST before writing any output.**
Set [VERDICT] based only on **currently open** issues (⚪️ Fixed entries do NOT count):
- `✅ APPROVE` — zero open 🔴 Critical AND zero open 🟡 Medium issues (only 🔵 Low / ✅ Positive / ⚪️ Fixed allowed)
- `❌ BLOCKED` — **one or more** open 🔴 Critical **OR** 🟡 Medium issues → **ALWAYS BLOCKED, no exceptions**

### 4. Output Format

Respond with exactly this structure (no extra lines outside it):

<details>
<summary>[VERDICT] - Claude Code Review</summary>

  > 🔴 **X** Critical · 🟡 **X** Medium · 🔵 **X** Low · ✅ **X** Positive · ⚪️ **X** Fixed

---

### 📋 PR Summary
- **What**: Brief description of the main changes.
- **Why**: Reason or motivation for the changes.
- **Scope**: Which files, components, directories are affected.
- **Details** (optional):
  - If the changes affect project structure, list new, deleted, or moved files/directories.
  - If there are important technical decisions, briefly describe them.
  - If there are breaking changes, state them explicitly.

---

### 🔒 Security Issues
  <details><summary>⚪️ Fixed [🔴/🟡/🔵]: [title]</summary>

  - **Was**: original severity description
  - **Fix applied**: what exactly was changed and where (`path/file.ext:line`)

  </details>
  <details><summary>[🔴 Critical/🟡 Medium/🔵 Low]: Issue Title</summary>

  - **File**: `path/file.ext:42`
  - **Why**: Problem explanation
  - **Fix**: Solution with code example

  </details>

---

### 🐛 Code Quality

---

### ⚡ Performance

---

### 📦 Dependencies

---

### 🎨 Style

---

### ✅ Positive Observations
- **Feature**: Description

---

### 📝 Documentation Updates Required
- **README.md**: [what and why]
- **CLAUDE.md**: [what and why]

---

</details>

### 5. Formatting Rules

- Severity in `<summary>`: assigned based on actual impact, **not** tied to category — 🔴 **Critical**: must fix before merge (data loss, security breach, broken functionality) · 🟡 **Medium**: should fix (incorrect behaviour, bad practice, meaningful technical debt) · 🔵 **Low**: nice to fix (style, naming, minor inconsistency)
- **Omit rule**: omit entire block (header + all entries + trailing `---`) if the block has no open issues AND no fixed items; omit `📝 Documentation` block if nothing to update; omit `✅ Positive Observations` block if none
- Issue and Fixed `<details>` entries may repeat as needed within a block; all issue blocks follow the same `<details>` structure as 🔒 Security Issues
- Always include file:line, impact, actionable fix; add before/after code examples where helpful
- **Issue counter**: replace each `X` with actual count (`0` if none); Fixed = total ⚪️ Fixed across all categories
- **Strict format**: output ONLY the structure from section 4 — do not add any extra lines, summaries, or sections outside it
""".strip()


def _read_file_if_exists(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as file_obj:
        return file_obj.read()


def _build_context_block(pr_title, commits, diff_text, base_branch, pr_comments):
    commit_messages = []
    for item in commits[:50]:
        message = ((item.get("commit") or {}).get("message")) or ""
        if message:
            commit_messages.append(message)

    comments_view = []
    for item in (pr_comments or [])[:100]:
        body = (item or {}).get("body") or ""
        if not body:
            continue
        comment_id = (item or {}).get("id")
        comments_view.append("Comment #{0}:\n{1}".format(comment_id, body))

    repo_readme = _read_file_if_exists("README.md")
    repo_claude = _read_file_if_exists("CLAUDE.md")

    return """Repository README.md:\n{0}\n\nRepository CLAUDE.md:\n{1}\n\nPR Title:\n{2}\n\nBase branch:\n{3}\n\nPR Commit Messages:\n{4}\n\nPR Comments:\n{5}\n\nPR Diff:\n{6}\n""".format(
        repo_readme or "(missing)",
        repo_claude or "(missing)",
        pr_title or "",
        base_branch or "main",
        "\n\n---\n\n".join(commit_messages) or "(none)",
        "\n\n---\n\n".join(comments_view) or "(none)",
        diff_text or "",
    )


def _extract_verdict(review_comment):
    if "❌ BLOCKED" in review_comment:
        return "blocked"
    if "✅ APPROVE" in review_comment:
        return "approve"
    return "unknown"


def run(pr_title, commits, diff_text, base_branch="", pr_comments=None):
    api_key = os.getenv("CLAUDE_API_KEY", "")
    if not api_key:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "⚠️ Claude review skipped: CLAUDE_API_KEY is not configured.",
            "should_comment": True,
        }

    if not ANTHROPIC_AVAILABLE:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "⚠️ Claude review skipped: anthropic package is not installed.",
            "should_comment": True,
        }

    Anthropic = importlib.import_module("anthropic").Anthropic
    try:
        client = Anthropic(api_key=api_key)
        context_block = _build_context_block(
            pr_title=pr_title,
            commits=commits,
            diff_text=diff_text,
            base_branch=base_branch,
            pr_comments=pr_comments or [],
        )

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=REVIEW_PROMPT_TEMPLATE,
            messages=[
                {
                    "role": "user",
                    "content": context_block,
                }
            ],
        )

        review_comment = ""
        for block in response.content:
            if getattr(block, "type", "") == "text":
                review_comment += block.text

        review_comment = (review_comment or "").strip()
        if not review_comment:
            raise ValueError("Claude returned an empty response")

        verdict = _extract_verdict(review_comment)
        has_violations = verdict == "blocked"

        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": has_violations,
            "comment": review_comment,
            "should_comment": True,
        }
    except Exception as e:
        return {
            "feature": FEATURE_KEY,
            "title_violations": [],
            "commit_violations": [],
            "comment_violations": [],
            "has_violations": False,
            "comment": "⚠️ Claude review skipped due to error: {0}".format(str(e)[:400]),
            "should_comment": True,
        }
