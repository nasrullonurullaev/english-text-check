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
    """
    from checks import ai_text_review_check

    return [ai_text_review_check]
