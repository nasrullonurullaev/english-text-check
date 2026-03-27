# english-text-check

AWS Lambda function for checking English-only text in Gitea pull requests.

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
