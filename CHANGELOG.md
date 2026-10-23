# Changelog

## Unreleased — proposed v0.1.0-rc.1

**Draft release notes; NO-GO for publication. No tag or GitHub Release exists.** See the [candidate runbook](docs/RELEASE_CANDIDATE.md) and [verification ledger](docs/RELEASE_VERIFICATION.md) for exact evidence and blockers.

### Available on the baseline main branch

- FastAPI API with LangGraph learning orchestration, QA, practice generation and mastery evaluation.
- PostgreSQL/PGVector storage, Alembic migrations, canonical taxonomy bootstrap and generic question import.
- Next.js 16.4.2 / React 19.3.0 web client and Taro mini-program client.
- Authentication regression checks, standalone backend test runner, public-data boundary checks and Docker service smoke.
- Loopback-only development Compose ports; Apache-2.0 code license and contributor/security guidance.
- Removal of unverified question JSON from current branch heads; two independently authored example questions.

### Proposed in review (not yet merged)

- [#29](https://github.com/Xiaomuw/Learning-assistant/pull/29): updated installation, release gates, dependency/history findings and truthful Codex for OSS application draft.
- [#30](https://github.com/Xiaomuw/Learning-assistant/pull/30): real PostgreSQL learning-cycle regression, preserved question option text, real FastAPI-to-Next SSE check, and Compose restart after deleting disposable volumes.
- [#31](https://github.com/Xiaomuw/Learning-assistant/pull/31): Requests/python-dotenv patch upgrades with local HTTP and configuration regressions.
- [#32](https://github.com/Xiaomuw/Learning-assistant/pull/32): PDF/multipart parser updates with original-document upload, rejection and cleanup regressions.
- [#33](https://github.com/Xiaomuw/Learning-assistant/pull/33): prevent chunk mapping overwrite across users/notebooks and shared cleanup deleting personal mappings; exercise URL ingestion and real PGVector with controlled embeddings. Existing lost mappings require owner-reviewed reimport from lawful originals.
- [#34](https://github.com/Xiaomuw/Learning-assistant/pull/34): upgrade FastAPI/Starlette together, enforce URL-encoded form limits, and verify multipart plus real HTTP SSE completion/disconnect compatibility. Combined local Python dependency audit with #31/#32 has no matched advisories; this does not clear the release gate.

Additional proposals: [#35](https://github.com/Xiaomuw/Learning-assistant/pull/35) patches compatible Web transitives and adds project CSS-pipeline regressions; [#36](https://github.com/Xiaomuw/Learning-assistant/pull/36) patches four Taro tooling transitives and runs the existing stream-client tests in CI. Both full npm audits still report unresolved findings; no framework major upgrade or audit suppression is included.

### Known limitations and migration notes


Live LLM/embedding quality, browser/device acceptance and production deployment remain unverified. RAG unit/fake tests do not demonstrate real retrieval quality. Python requirements are not fully transitively locked. Dependency alerts, license/asset review and historical question-bank rights remain open. The old question bank is outside the Apache-2.0 grant. React Hooks lint debt remains in issue #8.

Use a fresh isolated database, migrate to the current Alembic head and bootstrap canonical metadata before importing the synthetic examples. Take and restore-test backups before any future non-disposable upgrade. A code downgrade cannot undo lost or transformed data. See the runbook for environment versions, commands and restore limitations.
