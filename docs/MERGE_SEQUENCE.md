# Post-merge status and remaining release checks

This file records the merge order that was actually completed and the checks still required. It does not authorize deployment, history rewriting, or a release.

## Merges completed

1. [PR #6 — question-bank separation](https://github.com/Xiaomuw/Learning-assistant/pull/6) merged into main as a0dc819e8d4ff9db481ac8877b67105570829b8c. The five current question-bank JSON files were removed; two synthetic examples and generic import functionality remain.
2. [PR #3 — OSS readiness](https://github.com/Xiaomuw/Learning-assistant/pull/3) merged as a02e53c671d91b56599c32a7efa0a760f1a25a10. Apache-2.0, scope notes, English README, contributor/security guidance, Dependabot, CI and historical review documentation are on the default branch.
3. [PR #7 — Next.js 16 migration and real auth tests](https://github.com/Xiaomuw/Learning-assistant/pull/7) merged as 8290f0a2e6b8740104f44bc926d3da06812cb4cb. The web client uses Next.js 16.4.2 / React 19.3.0, with a committed lockfile and authentication regression checks.

## Historical evidence available

- [Question-data boundary and isolated PostgreSQL checks](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39636192111)
- [Quality checks on main](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39636191923)
- [Next.js migration verification](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39635544988)
- [Real backend authentication regression](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39635544928)

The auth test set includes 22 regression tests and 18 HTTP assertions through Next.js to real FastAPI and isolated PostgreSQL. SMTP is redirected to a local test sink; no external email delivery or paid LLM call is made.

## Remaining release blockers

- [x] Merged [PR #23](https://github.com/Xiaomuw/Learning-assistant/pull/23), [PR #24](https://github.com/Xiaomuw/Learning-assistant/pull/24), and [PR #25](https://github.com/Xiaomuw/Learning-assistant/pull/25); all three legacy branch heads now contain zero question-bank JSON files.
- [ ] Assess historical Git exposure separately. A normal deletion commit does not remove prior commits, clones, forks or caches. No history rewrite has been performed.
- [ ] Resolve source-rights/provenance concerns for the web-collected 530-question bank; it remains outside the Apache-2.0 grant.
- [x] Alembic expected-head check is implemented dynamically in `backend/scripts/rebuild_408_project_data.py`; PR #22 merged and isolated PostgreSQL checks passed.
- [ ] Finish full third-party dependency/license, embedded-asset, code ownership and authorized secret/history review.
- [x] PR #28 merged: development ports are loopback-only; clean-clone Compose smoke checks backend `/health`, frontend `/login`, anonymous auth rejection and port bindings.
- [ ] Test real LLM/RAG answers, browser/mobile flows, external email delivery, HTTPS/TLS, CORS/proxy and staging deployment. Real deterministic FastAPI→Next SSE is added separately in #30; it is not external-model acceptance.
- [ ] Address React Hooks lint exceptions and warnings tracked in [issue #8](https://github.com/Xiaomuw/Learning-assistant/issues/8).
- [ ] Publish a reproducible, owner-reviewed release only after these checks; no Release has been published yet.

Related trackers: [question-bank rights #5](https://github.com/Xiaomuw/Learning-assistant/issues/5), [Next.js/release follow-up #4](https://github.com/Xiaomuw/Learning-assistant/issues/4), [React Hooks debt #8](https://github.com/Xiaomuw/Learning-assistant/issues/8).

## Current review sequence (no automatic merging)

- Keep release/documentation changes in existing Draft [#29](https://github.com/Xiaomuw/Learning-assistant/pull/29).
- Review independent Draft [#30](https://github.com/Xiaomuw/Learning-assistant/pull/30) for the reproduced question-record persistence fix and database/SSE/restart regressions.
- Review independent Draft [#31](https://github.com/Xiaomuw/Learning-assistant/pull/31) for two narrowly scoped dependency updates.
- Existing Dependabot major upgrades and docs #2 remain separate; re-evaluate overlap and compatibility before any owner-approved merge.
- After any future merges, re-run the full workflow set on the combined candidate SHA. PR-level green checks do not certify that merged combination.

Use the [verification ledger](RELEASE_VERIFICATION.md) for baseline/head SHAs, current CI runs, local failures/skips and validation levels, rather than treating the older links above as current-head evidence. The [candidate runbook](RELEASE_CANDIDATE.md) proposes `v0.1.0-rc.1` but authorizes no tag, Release, image publication or deployment.

**Status: NO-GO.** Dependency findings, license/asset review, historical rights/exposure and live/staging acceptance remain unresolved.
