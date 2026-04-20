# english-text-check

AWS Lambda function for checking text quality in Gitea pull requests.

## Architecture

- `lambda_function.py` is the single entrypoint (webhook parsing, Gitea API calls, PR flow).
- `checks/` contains feature modules. Add a new file there and register it in `checks/__init__.py` to extend behavior in future without rewriting the Lambda flow.
- `checks/english_text_check.py` validates English-only text for PR title, commit messages, and code comments.
- `checks/pr_title_ai_review.py` reviews PR title quality and always posts feedback:
  - uses OpenAI when `OPENAI_API_KEY` is available,
  - uses a local fallback review when API is unavailable.

## PR title review feature

```bash
# Optional: enables OpenAI-backed review (default model: gpt-4o-mini)
export OPENAI_API_KEY="your_api_key"

# Optional: override model
export OPENAI_MODEL="gpt-4o-mini"
```

The check is always active, so PR title feedback is always posted in comments.

## Run tests locally

```bash
pytest -q
```

## CI

Tests run automatically on every pull request via GitHub Actions (`.github/workflows/tests.yml`).
