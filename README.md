# english-text-check

AWS Lambda function for checking pull request text quality in Gitea pull requests.

## Architecture

- `lambda_function.py` is the single entrypoint (webhook parsing, Gitea API calls, PR flow).
- `checks/` contains feature modules. Add a new file there and register it in `checks/__init__.py` to extend behavior without rewriting the Lambda flow.
- `checks/english_text_check.py` validates English-only text in PR title, commit messages, and code comments.
- `checks/ai_text_review_check.py` uses Claude to produce a structured PR review comment in `Claude Code Review` format based on:
  - repository docs (`README.md`, `CLAUDE.md`),
  - full PR diff,
  - PR title,
  - commit messages,
  - existing PR comments (to preserve and track previously reported issues).

## Environment variables

Required:

- `GITEA_BASE_URL`
- `GITEA_TOKEN`
- `WEBHOOK_SECRET`

Optional:

- `ORG_NAME` (default: `ONLYOFFICE`)
- `STATUS_CONTEXT` (default: `English-Text-Check`)
- `ALLOWED_ACTIONS` (default: `opened,reopened,synchronize,edited,synchronized`)

Claude review options:

- `CLAUDE_API_KEY` (required to call Claude)
- `CLAUDE_MODEL` (default: `claude-3-7-sonnet-latest`)
- `AI_REPOSITORY_WHITELIST` (comma-separated repo names where Claude review is enabled; default: `DocSpace-buildtools,document-server-package`)

`english_text_check` always runs for all repositories. `ai_text_review_check` runs only for repositories listed in `AI_REPOSITORY_WHITELIST`.

## Claude dependency

Install dependency for the AI feature:

```bash
pip install anthropic
```

## Run tests locally

```bash
pytest -q
```
