# Post-merge status and remaining release checks

This file records the merge order that was actually completed and the checks still required. It does not authorize deployment, history rewriting, or a release.

## Merges completed

1. [PR #6 — question-bank separation](https://github.com/Xiaomuw/Learning-assistant/pull/6) merged into main as a0dc819e8d4ff9db481ac8877b67105570829b8c. The five current question-bank JSON files were removed; two synthetic examples and generic import functionality remain.
2. [PR #3 — OSS readiness](https://github.com/Xiaomuw/Learning-assistant/pull/3) merged as a02e53c671d91b56599c32a7efa0a760f1a25a10. Apache-2.0, scope notes, English README, contributor/security guidance, Dependabot, CI and historical review documentation are on the default branch.
3. [PR #7 — Next.js 16 migration and real auth tests](https://github.com/Xiaomuw/Learning-assistant/pull/7) merged as 8290f0a2e6b8740104f44bc926d3da06812cb4cb. The web client uses Next.js 16.4.2 / React 19.3.0, with a committed lockfile and authentication regression checks.

## Evidence available

- [Question-data boundary and isolated PostgreSQL checks](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39636192111)
- [Quality checks on main](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39636191923)
- [Next.js migration verification](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39635544988)
- [Real backend authentication regression](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39635544928)

The auth test set includes 22 regression tests and 18 HTTP assertions through Next.js to real FastAPI and isolated PostgreSQL. SMTP is redirected to a local test sink; no external email delivery or paid LLM call is made.

## Remaining release blockers

- [ ] Remove or review current question-bank copies on codex/docker-production-deploy, codex/qa-408-flow-web-toggle, and mian (42 JSON files at its checked branch head).
- [ ] Assess historical Git exposure separately. A normal deletion commit does not remove prior commits, clones, forks or caches. No history rewrite has been performed.
- [ ] Resolve source-rights/provenance concerns for the web-collected 530-question bank; it remains outside the Apache-2.0 grant.
- [ ] Fix the hard-coded Alembic revision in backend/scripts/rebuild_408_project_data.py (tracked by review PR #22) and rerun the isolated PostgreSQL suite before merging that fix.
- [ ] Finish full third-party dependency/license, embedded-asset, code ownership and authorized secret/history review.
- [ ] Test real LLM/RAG answers and backend SSE, browser/mobile flows, external email delivery, HTTPS/TLS, CORS/proxy and staging deployment.
- [ ] Address React Hooks lint exceptions and warnings tracked in [issue #8](https://github.com/Xiaomuw/Learning-assistant/issues/8).
- [ ] Publish a reproducible, owner-reviewed release only after these checks; no release has been published yet.

Related trackers: [question-bank rights #5](https://github.com/Xiaomuw/Learning-assistant/issues/5), [Next.js/release follow-up #4](https://github.com/Xiaomuw/Learning-assistant/issues/4), [React Hooks debt #8](https://github.com/Xiaomuw/Learning-assistant/issues/8).

**Status:** code-level foundations merged; repository-wide data exposure and production readiness remain unresolved.