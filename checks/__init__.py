from checks import commit_message_advisor_check
from checks import english_text_check


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
      - `is_advisory`: bool (optional, defaults to False)
    """
    return [english_text_check, commit_message_advisor_check]
