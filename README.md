# english-text-check

AWS Lambda function for checking pull request text quality in Gitea pull requests.

## Architecture

- `lambda_function.py` is the single entrypoint (webhook parsing, Gitea API calls, PR flow).
- `checks/` contains feature modules. Add a new file there and register it in `checks/__init__.py` to extend behavior without rewriting the Lambda flow.
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
- `STATUS_CONTEXT` (default: `Claude Code PR Review`)
- `ALLOWED_ACTIONS` (default: `opened,reopened,synchronize,edited,synchronized`)
- `ALLOWED_REPOSITORIES` (default: empty, means all repositories in `ORG_NAME`; supports `repo` or `owner/repo`, comma-separated)

Claude review options:

- `CLAUDE_API_KEY` (required to call Claude)
- `CLAUDE_MODEL` (default: `claude-opus-4-7`)

Use `ALLOWED_REPOSITORIES` to enforce a whitelist of repositories where this Lambda is allowed to run.

## Claude dependency

Install dependency for the AI feature:

```bash
pip install anthropic
```

## Run tests locally

```bash
pytest -q
```
