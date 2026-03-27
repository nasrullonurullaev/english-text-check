from checks import english_text_check


def get_enabled_checks():
    """Registry of PR checks.

    To add a new feature later, add a module in `checks/` and include it here.
    """
    return [english_text_check]
