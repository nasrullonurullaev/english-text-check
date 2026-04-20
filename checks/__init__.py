from checks import english_text_check
from checks import pr_title_ai_review


def get_enabled_checks():
    """Registry of PR checks.

    Contract for every check module:
    - `run(pr_title, commits, diff_text) -> dict`
    - required keys:
      - `feature`, `title_violations`, `commit_violations`,
        `comment_violations`, `has_violations`, `comment`
      - optional `always_comment`
    """
    return [english_text_check, pr_title_ai_review]
