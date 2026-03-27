import re
import unicodedata

EXCLUDED_FILES = {".json", ".p7s", ".cjs", ".po", ".license", ".xml", ".md", ".resx"}
COMMENT_REGEX = re.compile(r"(?://|#|<!--|/\*|\*).+")
QUOTED_TEXT_REGEX = re.compile(r'(".*?"|\'.*?\')')
ALLOWED_SYMBOLS = {'↓', '↑', '←', '→', '⌘', '⌥', '©', '•', '—', '─'}


FEATURE_KEY = "english_text"


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


def run(pr_title, commits, diff_text):
    title_violations = extract_invalid_pr_title(pr_title)
    commit_violations = extract_invalid_commit_messages(commits)
    comment_violations = extract_non_ascii_comments(diff_text)

    return {
        "feature": FEATURE_KEY,
        "title_violations": title_violations,
        "commit_violations": commit_violations,
        "comment_violations": comment_violations,
        "has_violations": bool(title_violations or commit_violations or comment_violations),
        "comment": build_comment(title_violations, commit_violations, comment_violations),
    }
