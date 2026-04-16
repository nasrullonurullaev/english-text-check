# english-text-check

AWS Lambda function for checking pull requests in Gitea.

## What it checks

- **English text check**: validates PR title, commit messages and code comments for non-English characters.
- **Commit message quality check (AI)**: validates commit messages against common Git rules (subject/body separation, subject length, imperative mood, wrapping, etc.) using OpenAI Responses API.

## Architecture

- `lambda_function.py` is the single entrypoint (webhook parsing, Gitea API calls, PR flow).
- `checks/` contains feature modules. Add a new file there and register it in `checks/__init__.py`.
- `checks/english_text_check.py` contains the English text validation rules.
- `checks/commit_message_check.py` contains commit message quality validation with OpenAI.

## Required environment variables

- `GITEA_BASE_URL`
- `GITEA_TOKEN`
- `WEBHOOK_SECRET`

## Optional environment variables

- `ORG_NAME` (default: `ONLYOFFICE`)
- `STATUS_CONTEXT` (default: `English-Text-Check`)
- `ALLOWED_ACTIONS` (default: `opened,reopened,synchronize,edited,synchronized`)

### AI commit-message check

- `OPENAI_API_KEY` — enables commit message quality check when present.
- `OPENAI_MODEL` (default: `gpt-5`)
- `COMMIT_MESSAGE_AI_CHECK_ENABLED` (default: `true`)
- `MAX_REVIEWED_COMMITS` (default: `20`)

If `OPENAI_API_KEY` is missing (or the feature is disabled), the AI commit-message check is skipped.

## Run tests locally

```bash
pytest -q
```
