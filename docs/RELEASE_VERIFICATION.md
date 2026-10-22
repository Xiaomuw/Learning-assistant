# Release verification ledger — 2026-10-22

**Overall: NO-GO.** This ledger records observations, including failures and skipped checks. A checked documentation box is not test evidence. New work stays in Draft PRs for maintainer review; nothing was merged, released or deployed by this task.

## Baseline and existing work

The initial fresh clone was clean at main `712c0538571d01129c0f8b1fb5488b35c9df6058` (merge of #27). There were 30 remote branch heads, no Git tags, no published GitHub Releases, and 14 open PRs: docs #2/#29 plus Dependabot #9–#16 and #18–#21. #17 was not an open upgrade. Issues #4 (deployment/live acceptance), #5 (question rights/history) and #8 (Hooks lint debt) remain open.

PR #29 was already Draft at `bc1cf3ac2fb3a0b4b2b517a3131cddc4bf7a6d46`; its seven workflows were green. This task updates that branch instead of opening duplicate release-readiness docs. It does not auto-accept Dependabot major upgrades or merge #2. New Draft PRs #30–#33 are independent branches from the baseline, not evidence of changes already on main.

| Requirement / finding | Status | Evidence and remaining boundary |
| --- | --- | --- |
| Apache-2.0, contributor/security docs, English README | Completed and inspected | Merged #3; dependency/content licenses remain separate |
| Current-tree question-bank exclusion, two examples | Completed and verified | #6 and #23–#25; public-data CI; 30 initial remote heads contain zero question JSON in the affected directory |
| Next.js/React migration | Implemented and build/auth tested | #7; versions 16.4.2/19.3.0; deployment still incomplete |
| Loopback Compose ports / migration expectations / full-suite runner | Implemented and CI verified | #28/#22/#27; no need to recreate these workflows |
| Documentation state | Corrected in #29 | Removed stale Next 14, proposed-license/deletion and all-interface-port claims; exact evidence scope added |
| Persisted generated-question JSON | Reproduced bug; fix under review in #30 | Trace summarizer changed option text/list shapes; schema round-trip regression now protects it |
| Real DB learning cycle / actual SSE / empty-volume restart | Added in #30 | Deterministic generation/arithmetic; no external model claim |
| Third-party vulnerabilities | Partial mitigation in #31/#32 | Four patched Python pins; the combined local audit still flags Starlette. Web/Taro/image issues remain |
| Complete RAG upload→parse→embed→retrieve→citation pipeline | Controlled-embedding PGVector integration proposed in #33 | Actual URL parsing, chunking, vector storage/search and source metadata; real-provider quality and browser citation rendering remain unverified |
| Python transitive lock / immutable images / image scanning | Not complete | Fresh installation success is date/environment-specific |
| Licenses, copied assets and history | Partial inventory, unresolved | See dedicated reviews; not lawful-redistribution clearance |
| Live model/embedding, SMTP, WeChat and staging | Credentials/resources needed; not run | Owner sandbox keys, explicit spending authorization, real app configuration and disposable deployment target |
| Key rotation, history rewrite, legal remediation | Owner decision; not suitable for automatic action | No force push, remote deletion, credential revocation or legal conclusion |

## Evidence levels

1. **Unit/Fake/SQLite:** deterministic models/retrievers, framework mocks, in-memory repositories or SQLite. These verify logic/contracts, not provider behavior.
2. **Isolated PostgreSQL / real HTTP:** disposable database/schema, actual FastAPI/Next HTTP processes and local SMTP sink. In #30 deterministic SSE uses the real graph and transport, but no LLM.
3. **Real external model/services:** not run. No paid model, embedding, web-search or external mail API was called.
4. **Full browser/device/deployment:** not run in this task. Historical screenshots do not validate current code or target deployment.

## Previously completed hosted runs, read and checked

The following runs are at PR #29's original doc-only head `bc1cf3a`, based on baseline main. They are not runs on a later changed PR head.

| Workflow / actual command boundary | Result | Run |
| --- | --- | --- |
| Backend requirements install, migration diagnostic, bootstrap; `python scripts/run_isolated_unittests.py` | PASS: 69 modules, strict disposable PostgreSQL | [39742007290](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39742007290) |
| Clean-clone Compose build/start/health/login/auth/loopback bindings | PASS, first boot only on this head | [39742007304](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39742007304) |
| Real authentication regressions + `python scripts/smoke_real_auth.py --allow-disposable-db` | PASS: 22 regression tests and 18 HTTP assertions; local SMTP | [39742007279](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39742007279) |
| Next lint/typecheck/build/fake proxy smoke, production Docker login, prod npm audit | PASS; production npm audit 0 | [39742007253](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39742007253) |
| Public-data unit tests, synthetic import/rebuild on isolated PostgreSQL | PASS | [39742007250](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39742007250) |
| Python architecture/provenance, Web lint/build, Taro lint/typecheck/build | PASS; Web lint has 12 warnings | [39742007248](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39742007248) |
| Development Compose isolation tests | PASS | [39742007343](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39742007343) |

Exact baseline main also has successful [backend full-suite](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39709334122), [public-data](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39709334034), [quality](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39709334030) and [Compose-isolation](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39709333980) runs. Some workflows trigger only on PRs; do not relabel those runs as main runs.

## New PR evidence

- [#30](https://github.com/Xiaomuw/Learning-assistant/pull/30), initial `3efe1a1`: [backend run 39799693443](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39799693443) failed the new PostgreSQL QuestionItem validation. It exposed stored option text replaced by character counts. The next `6eb2e04` run exposed quality-report lists changed to preview dictionaries. Neither assertion was weakened; the domain-field persistence bug was fixed, while trace redaction remains intact. The test harness was also corrected to provide required quality-report fields and use production-compatible transaction lifetime.
- Initial #30 [real HTTP run](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39799693258) and [clean-volume restart run](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39799693309) passed. These include 24 real HTTP assertions (18 auth + six SSE checks) and two Compose boots/migration/bootstrap passes.
- On `4156106`, the new PostgreSQL learning cycle passed, but an existing grace-response test intermittently observed the intentionally nonblocking persistence task before completion. The TestClient had been closing its per-request event loop. #30 now keeps that client context alive and waits on the actual completion callback with a bounded event; the final `completed` assertion is unchanged. All 50 chat tests and 25 targeted repetitions passed locally.
- #30 latest code head: `a76d36d6740548d6ce6ce759a6bffb077a998c21`. All seven exact-head workflows passed; see links below. Maintainer review is still required.
- [#31](https://github.com/Xiaomuw/Learning-assistant/pull/31), `f38876afdea44f4d4fc0cd6dffa9ad889043d69d`: Requests/python-dotenv patch pins and two boundary regressions. Fresh installation, `pip check`, and 37 related local tests passed. Re-audit reduced affected Python packages from five to three; it did not clear the release gate.

#31 exact-head hosted results: all seven workflows passed at `f38876afdea44f4d4fc0cd6dffa9ad889043d69d`.

| Workflow | Run |
| --- | --- |
| Backend full suite (70 modules, including dependency regressions) | [39801330700](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39801330700) |
| Real auth | [39801331249](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39801331249) |
| Clean Compose | [39801331238](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39801331238) |
| Quality | [39801330705](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39801330705) |
| Next migration | [39801330480](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39801330480) |
| Public-data boundary | [39801332447](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39801332447) |
| Compose isolation | [39801330996](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39801330996) |

#30 exact-head hosted results: all seven workflows passed at `a76d36d6740548d6ce6ce759a6bffb077a998c21`.

| Workflow | Run |
| --- | --- |
| Backend full suite (70 modules, strict PostgreSQL) | [39804655924](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39804655924) |
| Real auth + deterministic SSE (24 HTTP assertions) | [39804656093](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39804656093) |
| Clean Compose, migration/bootstrap and empty-volume restart | [39804655926](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39804655926) |
| Quality | [39804656148](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39804656148) |
| Next migration | [39804656167](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39804656167) |
| Public-data boundary | [39804655956](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39804655956) |
| Compose isolation | [39804655965](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39804655965) |


**PR #29 baseline CI blocker:** the documentation commit `e5784bae8d47ed9a1701cbb371c57376246bf0ec` passed six workflows, but [full-suite run 39805461739](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39805461739) failed with 68/69 modules passing. The failure was the existing `test_chat_sync_returns_completed_when_finished_during_grace` assertion (job still pending when the request-scoped TestClient portal closed). The callback/lifecycle fix is already green in independent #30; it is not included in this documentation branch. This known baseline failure is retained instead of rerunning until green. Review #30's fix before accepting the corresponding full-suite gate on a future combined candidate. The six successful #29 runs are [auth](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39805461876), [Compose](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39805461800), [quality](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39805461771), [Next](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39805461759), [data](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39805461755), and [isolation](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39805461790). This paragraph is a documentation-only follow-up; inspect its own head's checks as well.

Each PR targets main and remains Draft. Re-run the combined final main/candidate SHA after any future merges; independently passing branches do not prove their combination.

## Fresh local checks and their limits

These were run from the clean baseline clone using new virtual environments and npm cache directories; no old database or build cache was used. Local runtime: Python 3.12.14, Node 24.19.0, npm 11.9.0. This execution host has no Docker daemon/CLI or PostgreSQL server; database/container evidence above comes from actual hosted Actions.

| Working directory / command | Observed result |
| --- | --- |
| root: `python3 -m venv <fresh-env>`; `<fresh-env>/bin/python -m pip install --no-cache-dir -r backend/requirements.txt` | PASS; 95 resolved distributions; installed packages independently checked |
| `frontend`: `npm ci --cache <new-cache>` | PASS |
| `frontend`: `npm run lint`; `npm run typecheck` | PASS; 0 lint errors, 12 warnings |
| `frontend`: `NEXT_TELEMETRY_DISABLED=1 INTERNAL_API_BASE=http://127.0.0.1:18080/api npm run build` | PASS |
| `frontend`: `npm run smoke:proxy` | PASS, fake upstream including simulated SSE |
| `frontend-weapp`: `npm ci --cache <new-cache>`; `npm run typecheck`; `npm run lint`; `npm run build:weapp`; `npm run test:chat-stream` | PASS; tourist build + local stream-client tests, not real WeChat acceptance |
| `backend`: `python scripts/run_isolated_unittests.py` without DATABASE_URL/TEST_DATABASE_URL | NOT full-suite acceptance: 68 modules passed, one failed on missing DATABASE_URL; database tests skipped |
| `backend`: `DATABASE_URL=postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__ python -m unittest tests.test_router_rules -v` | The five configuration-blocked router tests passed; placeholder does not enable DB integration |
| #30 `backend`: `python -m unittest tests.test_learning_cycle_postgres -v` without TEST_DATABASE_URL | SKIPPED locally; strict PostgreSQL hosted gate required |
| #30 `backend`: `python -m unittest tests.test_graph_persistence_repositories -v` | PASS: 18 SQLite regressions including question fields and retained event/trace redaction |
| #30 local diagnostic of the same compiled graph cycle using SQLite | PASS: one diagnostic; does not replace PostgreSQL test |
| #31 fresh environment: requirements install; `python -m pip check` | PASS |
| #31 `backend`: `DATABASE_URL=postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__ python -m unittest tests.test_http_env_dependencies tests.test_env_validation tests.test_mcp_runtime tests.test_ingest_service -v` | PASS: 37; HTTP is a local test server, ingest vector/provider boundaries are mocked |
| #30 code with #31 dependency environment: repository/chat tests, each in a separate interpreter | PASS: 18 + 50; local boundary checks, not combined-branch hosted acceptance |
| #29 docs: architecture tests; public-data/provenance tests; local Markdown links; isolated execution of RC environment snippet; application character counts; `git diff --check` | PASS: 9 architecture + 12 data tests; links/snippet/counts/diff valid |
| #29 docs: `python scripts/audit_question_bank_provenance.py --release-gate` | Expected exit 2: current questions 0, historical ledger 530 unresolved; NO-GO retained |
| Dependency/security/license commands | Executed; findings retained in [review](DEPENDENCY_SECURITY_REVIEW.md), not suppressed |

## Business-path coverage map

| Path | Existing / added evidence | Still missing |
| --- | --- | --- |
| Question → route → QA | Router/orchestrator/QA graph unit and contract tests; #30 arithmetic through real HTTP/SSE | Live model answer quality and actual-browser interaction |
| Legal source → parser → chunks → vector retrieval → citation | #32 real multipart/PDF parsing with fake storage; #33 real URL parsing/PGVector with controlled embeddings and source metadata; see exact-head results below | Separate real-provider evaluation and browser citation rendering |
| Concept → question → validation → save | Graph unit tests; #30 actual compiled deterministic graph and real PostgreSQL schema round-trip | Live-model generation/quality; user answer submission connected to this graph-generated item through HTTP |
| Answer → event/attempt → mastery → query | Practice/mastery tests; #30 persisted events, idempotent attempts, mastery update/replay and user isolation | Full browser exercise flow and combined HTTP answer-to-mastery acceptance |
| FastAPI SSE → Next proxy → consumer | Existing fake-proxy tests and Taro parser tests; #30 actual authenticated server-to-proxy SSE | Browser/mobile rendering, reconnect/cancellation under deployed proxies, live-model latency/backpressure |

## Owner-only and manual acceptance

Use owner-approved sandbox credentials and synthetic documents for a live model/embedding run; record provider/model versions, cost budget, expected citations, refusal behavior and errors without keys or private content. On an isolated staging target, exercise registration/external email, login/refresh/logout, upload/retrieval/citations, generated practice/answer/mastery, SSE cancellation/reconnect, CORS, secure cookies, TLS and trusted proxies. Test WeChat with the real AppID in its developer tools/device. Rehearse backup restoration and startup from a clean volume. None of these are marked passed here.

Historical rights remediation, real credential rotation, history rewriting, publishing and application submission remain explicit owner decisions. No request for those permissions is needed to review these Draft PRs.

## Follow-up: parser dependencies and PGVector isolation

Main remained `712c0538571d01129c0f8b1fb5488b35c9df6058`; #29–#31 remained open Drafts when this follow-up began. #32/#33 were added for distinct parser-dependency and RAG-isolation scopes. No PR was merged.

### Parser patch #32

Head: `bf29dc5e870514b4a0db7907b99e2287af5e5c8c`. All seven workflows passed:

| Workflow | Run |
| --- | --- |
| Backend full suite, 70 modules incl. seven upload parser regressions | [39808693093](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39808693093) |
| Auth | [39808693159](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39808693159) |
| Next migration | [39808693099](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39808693099) |
| Public data | [39808693119](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39808693119) |
| Quality | [39808693124](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39808693124) |
| Clean Compose | [39808693101](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39808693101) |
| Compose isolation | [39808693075](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39808693075) |

Fresh Python 3.12.14 uncached install and `pip check` passed. From `backend`:

```bash
python -m unittest tests.test_upload_parsers tests.test_ingest_service -v
```

14 tests passed. A separate fresh environment combining #31/#32 requirements passed these 14 plus 30 tests from `tests.test_http_env_dependencies tests.test_env_validation tests.test_mcp_runtime` (with the documented placeholder DATABASE_URL). Initial invocations started before installation finished and failed module imports; those incomplete-environment results, including an incomplete dependency inventory, were discarded. Only the completed installation's 96-distribution inventory and subsequent tests are acceptance evidence. Combined full hosted CI is still required after any owner-approved merges.

### PGVector and mapping isolation #33

The initial [39809342862](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39809342862) run failed 1/70 modules: the test used a noncanonical subject, which the application normalizes to data-structure. The fixture now creates the supported computer-network subject. The HTTP success/persistence assertions were retained.

Two additional failures were reproduced locally before correction:

- Owner/notebook identity regression: four scopes generated one kb_chunk primary key (`1 != 4`), allowing one user's mapping to overwrite another's. Mapping IDs now hash subject, owner and vector ID, while vector/citation IDs remain unchanged.
- Real SQLite repository regression: replacing one shared source deleted three rows (`3 != 1`), including personal mappings. Shared cleanup now selects only absent/empty owners; personal cleanup remains owner-specific.

24 taxonomy/vector/configuration tests pass:

```bash
cd backend
python -m unittest tests.test_knowledge_taxonomy tests.test_ingest_taxonomy_mapping tests.test_retrieval_vector_contract tests.test_postgres_test_utils -v
python -m unittest tests.test_rag_ingestion_postgres -v
```

The second command skips locally without TEST_DATABASE_URL; this is not PostgreSQL acceptance. CI runs it with POSTGRES_TEST_STRICT=true in the existing disposable pgvector service. Its unique database is created from template0, migrated to Alembic head and dropped after pools close. The fixture rejects non-loopback, non-test and query-overridden DSNs before connecting. HTML is original and served only on loopback; auth and embeddings are controlled test substitutes. The actual parser, chunker, database, cosine search and citation source metadata are exercised; keyword fallback is forbidden in the positive vector assertions. No paid/external model is involved.

Exact-head hosted results: all seven workflows passed at `df6aacae5bb3f00b39782c6983ba2f8d9e9263b9`. The full-suite log confirms both new PostgreSQL tests passed and **70/70 modules** succeeded, including fresh migrations and test-database cleanup.

| Workflow | Run |
| --- | --- |
| Backend full suite | [39810513381](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39810513381) |
| Auth | [39810513206](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39810513206) |
| Clean Compose | [39810513400](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39810513400) |
| Quality | [39810513158](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39810513158) |
| Public data | [39810513222](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39810513222) |
| Next migration | [39810513255](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39810513255) |
| Compose isolation | [39810513163](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39810513163) |

Documentation follow-up checks: all changed Markdown local links and both audit JSON snapshots validated; 12 public-data/Compose/provenance tests passed. The release-gate command still exits 2 with 530 unresolved historical questions. No source data was reintroduced.

No automatic backfill occurs. Owners must back up and reimport lawful originals to restore previously overwritten/deleted mappings; lost content cannot be recreated from the missing row. This review did not access or repair existing learner data. Full browser citation rendering, real embedding relevance and live provider evaluation remain open.
