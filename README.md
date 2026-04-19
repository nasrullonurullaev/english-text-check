# english-text-check

AWS Lambda function for checking text quality in Gitea pull requests.

## Architecture

- `lambda_function.py` is the single entrypoint (webhook parsing, Gitea API calls, PR flow).
- `checks/` contains feature modules. Add a new file there and register it in `checks/__init__.py` to extend behavior in future without rewriting the Lambda flow.
- `checks/english_text_check.py` contains English text validation for PR title, commit messages, and code comments.
- `checks/pr_title_ai_review.py` (optional feature) reviews PR title style with OpenAI and leaves a comment with either ✅ feedback or ❌ advice + example title.

## Optional AI PR title review feature

Set these variables to enable the new feature:

```bash
export ENABLE_PR_TITLE_AI_CHECK=true
export OPENAI_API_KEY="your_api_key"
# Optional, default is gpt-4o-mini
export OPENAI_MODEL="gpt-4o-mini"
```

When enabled, Lambda will:
- call OpenAI to evaluate PR title quality,
- always post a review comment from this check,
- keep existing checks working as before.

## Run tests locally

```bash
pytest -q
```

## CI

Tests run automatically on every pull request via GitHub Actions (`.github/workflows/tests.yml`).
