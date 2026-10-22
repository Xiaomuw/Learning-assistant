# Data, Configuration and Release Audit

**Status: BLOCKED for public release.** This is an evidence and action register, not a completed legal/security audit.

## Verified observations

| Area | Finding | Next action |
| --- | --- | --- |
| Former 408 practice bank and other branches | After merged PR #6, current `main` has **0 question-bank JSONs** under `data/practice_questions/`. The older `codex/docker-production-deploy` and `codex/qa-408-flow-web-toggle` branches each still have five; `mian` has **42 JSON files**, including batch/v2 content and a cleanup report. | Keep current main clear; review/remove unverified content from other branch heads and separately assess historical Git copies. [Branch inventory](GIT_HISTORY_EXPOSURE_REVIEW.md). |
| Untracked curriculum | `backend/app/application/notebooks/curriculum_seed.py` loads packages from `backend/storage/data/curriculum/`, under the ignored `backend/storage/` path. | Make fresh-clone tests independent of unpublished data, or supply legally redistributable fixtures. |
| Dev configuration | `docker-compose.yml` publishes Postgres 5434, backend 8003, frontend 3003 and uses a predictable database fallback password. | Restrict host access or bind loopback; never reuse defaults in production. |
| Mini-program | The tracked project config included a specific developer AppID; this PR proposes `touristappid`. | Provide a local AppID via `TARO_APP_ID` / `WECHAT_MINI_APP_ID`, with private configuration ignored. |
| Third-party code and packages | A complete resolved dependency-license/vulnerability and embedded-asset review has not been run. | Audit direct/transitive dependency licenses, advisories, assets and attribution. |
| Known Next.js dependency vulnerability range | `frontend/package.json` pins `next@14.2.29`, a version included in publicly disclosed affected ranges. Actual exploitability depends on deployment/features. | Track [security upgrade #4](https://github.com/Xiaomuw/Learning-assistant/issues/4); upgrade to an actively patched major release with regression checks. |
| Credentials and ownership | A comprehensive historical secret scan and code-contributor ownership review has not been verified. | Audit authorized repository and Git history; revoke any exposed secrets. |

Tracked dataset rights: [issue #5](https://github.com/Xiaomuw/Learning-assistant/issues/5).

## Evidence snapshot (2026-10-21)

**Owner-confirmed method:** AI searched existing online question banks and reorganized the retrieved material into 530 questions. The use of third-party online banks is confirmed; exact original URLs, rightsholders and redistribution permissions have **not** been established. Do not classify these records as independently AI-authored original questions.

Historical inventory from the **pre-PR #6 main tree** of `data/practice_questions/all_408.json` and its four subject mirrors:

| Finding | Verified result |
| --- | --- |
| Canonical questions | 530 records, with 530 unique `question_id` values |
| Concepts | 53 concepts, exactly 10 questions per concept |
| Subjects | Data structures 160, operating systems 140, computer networks 120, computer organization 110 |
| Difficulty labels | `basic` 159, `medium` 265, `hard` 106 |
| Subject mirrors | All four mirrors total 530 records; no missing IDs, repeated IDs across mirrors or JSON field mismatches against canonical records |
| Keys available on every canonical record | `question_id`, `concept_id`, `difficulty`, `stem`, `options`, `answer`, `explanation`, `knowledge_points`, `common_trap` |
| Provenance metadata | **0/530** records contain source, author, citation, URL, copyright/license, model or generation-prompt keys |
| Exact identical question stems | No exact duplicates found using a normalized-whitespace comparison |

**Important limitations:** A lack of exact duplicate text does not establish originality. No independent web/source matching, copyright ownership review, model prompt/history audit, or legal review has been completed. These findings describe the checked repository snapshot; they do not certify the lawfulness of publication.

**Disposition:** `AI-assisted web search of existing question banks — reorganization of retrieved content — third-party provenance/permissions unverified — public redistribution not cleared`. All 530 entries are listed as **REVIEW_REQUIRED** in [data/provenance/408-source-review.csv](../data/provenance/408-source-review.csv). This is a bookkeeping status, not an infringement determination. Keep the dataset outside Apache-2.0 and do not ship an uncleared release. See the [remediation plan](QUESTION_BANK_REMEDIATION.md).

**Next evidence needed:** original source URLs (if recoverable), relevant source licenses/terms, permission for copying/adapting/distribution, and private search/prompt records. Web discoverability or AI rewording alone does not grant reuse rights. Do not publish private evidence, credentials or additional third-party question text.

## Mechanical checks (not legal clearance)

Use `python scripts/audit_question_bank_provenance.py --json`. When the old files still exist, it validates the canonical/subject mirrors and matching ledger. Once **all five** files have been removed, it checks that no partial mirror or newly unreviewed JSON has appeared and retains the 530-ID ledger solely as **historical review metadata**, rather than reporting those entries as missing source files. The report separates `current_tree_data_boundary_passes` from the broader `release_gate_passes`; the latter **remains false** for the historically uncleared retired corpus. The `--release-gate` mode intentionally blocks a release and does not establish legal compliance.

PR #6 has now been merged and the current main tree is clean. The remaining release blocker is the unreviewed material on older branch heads and in historical commits; see [GIT_HISTORY_EXPOSURE_REVIEW.md](GIT_HISTORY_EXPOSURE_REVIEW.md).

## Historical exposure and merge coordination

See [historical Git exposure review](GIT_HISTORY_EXPOSURE_REVIEW.md) and [two-PR integration sequence](MERGE_SEQUENCE.md). Do **not** rewrite Git history, move protected refs or force-push as part of this audit PR.

## Dataset provenance register (owner-completed)

Record **for each data source and any copied question**:

- Original source identifier, author/rightsholder, and content creation method (independent, AI-assisted, adapted or copied).
- Documentary permission, including rights to publish, adapt and redistribute wording, options and explanations.
- License version, attribution/copyright requirements and any restrictions.
- Evidence reference stored outside the public repository if private.
- Decision: **APPROVED**, **REPLACE**, **REMOVE**, or **REVIEW**.

Excluding a dataset from the repository Apache-2.0 scope does **not** authorize its existing public distribution. If the right to distribute cannot be demonstrated, remove or replace the content in the public tree and plan history remediation where appropriate. History rewriting may break clones, forks and commit links; deletion does not revoke leaked credentials.

## Minimum release gates

- [ ] Audit dataset provenance, upstream ownership and rights of all original/borrowed code and assets.
- [x] Merge the Next.js 16.4.2 / React 19.3.0 security migration; its CI, Docker login-route check, production dependency audit and real auth regression jobs passed before merge ([PR #7](https://github.com/Xiaomuw/Learning-assistant/pull/7)).
- [ ] Complete remaining browser/mobile, real-model RAG/SSE, public TLS/CORS/proxy and staging checks ([issue #4](https://github.com/Xiaomuw/Learning-assistant/issues/4)).
- [ ] Review licenses and active advisories of resolved direct/transitive dependencies.
- [ ] Scan current tree and Git history for credentials and sensitive data, remediate if discovered.
- [ ] Run a fresh-clone build with independent, redistributable test fixtures.
- [ ] Pass expanded CI plus full backend/unit, isolated Postgres integration, smoke and core UI flow tests.
- [ ] Verify safe development/production configuration with non-default credentials.
- [ ] Publish owner-approved changelog, limitations, source notices and release tag.

See [open-source readiness](OPEN_SOURCE_READINESS.md); a successful static check is not release approval.
