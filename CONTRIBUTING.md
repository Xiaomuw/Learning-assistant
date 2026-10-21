# Contributing to Learning Assistant

Thank you for your interest in the project. Small, focused improvements are easier to review and maintain.

## Before contributing

1. Read [README.en.md](README.en.md), [AGENTS.md](AGENTS.md) and [LICENSE-SCOPE.md](LICENSE-SCOPE.md).
2. Search existing issues and pull requests to avoid duplicate work.
3. Use the issue templates for reproducible bugs or feature proposals. Discuss large architectural changes before implementing them.
4. Make sure you have the rights to contribute the code, tests, sample data, or documentation you submit. **Do not add unlicensed examination questions or copied course materials.**

## Development workflow

1. Fork the repository or create a feature branch.
2. Make one logical change per pull request, including tests when behavior changes.
3. Keep the established separation among interfaces, application, orchestration, domains, services and infrastructure.
4. Do not add real credentials, uploaded study material, personal data or production database dumps to commits.
5. Run checks relevant to your changes and record which checks ran. Never report a test as passed unless it actually ran.

```bash
# Backend and LangGraph (requires the documented Python environment):
make test-backend
make test-graphs
make eval-graphs

# Web and mini-program clients (requires npm dependencies):
make check-frontend
make check-weapp

# Inspect whitespace errors:
git diff --check
```

Some backend checks require an intentionally provisioned local test environment, and the PostgreSQL suite requires `TEST_DATABASE_URL` pointing to a **disposable test database**. Do not run smoke tests against production or user data.

## Pull request checklist

- Explain the motivation and affected module.
- Link a relevant issue when one exists.
- Provide tests or a clear reason why they are not applicable.
- Include screenshots for UI changes, with private user information removed.
- Note config, database migration and backwards-compatibility impacts.
- Identify any external source code, images, datasets or licensed material.

## Licensing contributions

By submitting a contribution, you confirm you have the right to submit it and understand that accepted original project contributions are made available under Apache-2.0, unless a different arrangement is explicitly documented by maintainers. Existing third-party notices and licenses remain in force; see [LICENSE-SCOPE.md](LICENSE-SCOPE.md).

Review and release decisions are handled by project maintainers. There is no guarantee of an immediate review or acceptance.
