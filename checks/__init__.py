import os

from checks import english_text_check
from checks import pr_title_ai_review


def _is_truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def get_enabled_checks():
    """Registry of PR checks.

    To add a new feature later, add a module in `checks/` and include it here.

    Contract for every check module:
    - `run(pr_title, commits, diff_text) -> dict`
    - return dict must contain:
      - `feature`: str
      - `title_violations`: list
      - `commit_violations`: list
      - `comment_violations`: list
      - `has_violations`: bool
      - `comment`: str
      - optional `always_comment`: bool
    """
    checks = [english_text_check]

    if _is_truthy(os.getenv("ENABLE_PR_TITLE_AI_CHECK", "false")):
        checks.append(pr_title_ai_review)

    return checks
