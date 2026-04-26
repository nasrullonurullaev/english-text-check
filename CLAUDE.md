# CLAUDE.md

## Repository context

- Runtime: AWS Lambda (Python).
- SCM platform: Gitea pull requests.
- Entry point: `lambda_function.py`.
- Extensible checks live in `checks/` and are aggregated into one status + one managed PR comment.

## Review focus

When generating a PR review comment, prioritize:

1. Security-sensitive changes in webhook handling and API requests.
2. Correctness of PR status logic (`pending` -> final status).
3. Signal quality of reviewer feedback (clear severity, actionable fixes, file:line references).
4. Respecting existing review history by recognizing fixed vs still-open issues.

## Coding standards

- Keep modules small and single-purpose.
- Prefer explicit helper functions over deeply nested logic.
- Return stable data contracts from checks (`feature`, violations arrays, `has_violations`, `comment`, `should_comment`).
- On external AI errors, degrade gracefully and keep Lambda operational.
- Keep comments concise and automation-friendly.
