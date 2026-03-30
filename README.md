# english-text-check

AWS Lambda function for checking English-only text in Gitea pull requests.

It can also provide **non-blocking commit message recommendations** using an OpenAI-compatible API.

## Architecture

- `lambda_function.py` is the single entrypoint (webhook parsing, Gitea API calls, PR flow).
- `checks/` contains feature modules. Add a new file there and register it in `checks/__init__.py` to extend behavior in future without rewriting the Lambda flow.
- `checks/english_text_check.py` contains the current English text validation rules.

## Run tests locally

```bash
pytest -q
```

## CI

Tests run automatically on every pull request via GitHub Actions (`.github/workflows/tests.yml`).


## Optional: AI commit message advisor (recommendations only)

The advisor checks commit messages against the classic 7 rules (subject/body
split, subject length, imperative mood, etc.) and posts suggestions as a PR
comment. It **never fails** the status check by itself.
If `OPENAI_API_KEY` is not configured (or API call fails), it falls back to a
simple local recommendation (`suggested subject` or `OK`).

Environment variables:

- `OPENAI_API_KEY=<your token>` to authenticate with the model provider.
- `COMMIT_MESSAGE_ADVISOR_MODEL=gpt-4o-mini` (default) for a fast/cheap model.
- `OPENAI_BASE_URL=https://api.openai.com/v1` for OpenAI-compatible endpoints.
- `COMMIT_MESSAGE_ADVISOR_MAX_COMMITS=20` to limit analyzed commits per PR.
