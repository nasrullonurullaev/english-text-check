# english-text-check

AWS Lambda function for checking pull request text quality in Gitea pull requests.

## Architecture

- `lambda_function.py` is the single entrypoint (webhook parsing, Gitea API calls, PR flow).
- `checks/` contains feature modules. Add a new file there and register it in `checks/__init__.py` to extend behavior without rewriting the Lambda flow.
- `checks/english_text_check.py` validates English-only text in PR title, commit messages, and code comments.
- `checks/ai_text_review_check.py` uses OpenAI to review PR title and commit messages and posts a human-friendly PR comment:
  - ✅ if everything looks good;
  - ❌ with suggestions and example wording when issues are found.

## Environment variables

Required:

- `GITEA_BASE_URL`
- `GITEA_TOKEN`
- `WEBHOOK_SECRET`

Optional:

- `ORG_NAME` (default: `ONLYOFFICE`)
- `STATUS_CONTEXT` (default: `English-Text-Check`)
- `ALLOWED_ACTIONS` (default: `opened,reopened,synchronize,edited,synchronized`)

AI review options:

- `OPENAI_API_KEY` (required to actually call OpenAI)
- `OPENAI_MODEL` (default: `gpt-5-mini`)
- `OPENAI_TIMEOUT_SECONDS` (default: `20`)
- `OPENAI_MAX_RETRIES` (default: `2`)
- `OPENAI_RETRY_DELAY_SECONDS` (default: `0.8`)
- `AI_MAX_TITLE_CHARS` (default: `300`)
- `AI_MAX_COMMIT_MESSAGE_CHARS` (default: `2000`)
- `AI_MAX_COMMITS_TO_REVIEW` (default: `20`)

> AI review is fail-closed: if OpenAI call fails at runtime, the check reports failure.

## OpenAI dependency

Install dependency for the AI feature:

```bash
pip install openai
```

## Run tests locally

```bash
pytest -q
```

## CI

Tests run automatically on every pull request via GitHub Actions (`.github/workflows/tests.yml`).
