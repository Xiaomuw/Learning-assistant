# Release verification ledger — updated 2026-10-23

**Overall: NO-GO.** This ledger records observations, including failures and skipped checks. A checked documentation box is not test evidence. New work stays in Draft PRs for maintainer review; nothing was merged, released or deployed by this task.

## Baseline and existing work

The initial fresh clone was clean at main `712c0538571d01129c0f8b1fb5488b35c9df6058` (merge of #27). There were 30 remote branch heads, no Git tags, no published GitHub Releases, and 14 open PRs: docs #2/#29 plus Dependabot #9–#16 and #18–#21. #17 was not an open upgrade. Issues #4 (deployment/live acceptance), #5 (question rights/history) and #8 (Hooks lint debt) remain open.

PR #29 was already Draft at `bc1cf3ac2fb3a0b4b2b517a3131cddc4bf7a6d46`; its seven workflows were green. This task updates that branch instead of opening duplicate release-readiness docs. It does not auto-accept Dependabot major upgrades or merge #2. New Draft PRs #30–#37 are independent branches from the baseline, not evidence of changes already on main.

| Requirement / finding | Status | Evidence and remaining boundary |
| --- | --- | --- |
| Apache-2.0, contributor/security docs, English README | Completed and inspected | Merged #3; dependency/content licenses remain separate |
| Current-tree question-bank exclusion, two examples | Completed and verified | #6 and #23–#25; public-data CI; 30 initial remote heads contain zero question JSON in the affected directory |
| Next.js/React migration | Implemented and build/auth tested | #7; versions 16.4.2/19.3.0; deployment still incomplete |
| Loopback Compose ports / migration expectations / full-suite runner | Implemented and CI verified | #28/#22/#27; no need to recreate these workflows |
| Documentation state | Corrected in #29 | Removed stale Next 14, proposed-license/deletion and all-interface-port claims; exact evidence scope added |
| Persisted generated-question JSON | Reproduced bug; fix under review in #30 | Trace summarizer changed option text/list shapes; schema round-trip regression now protects it |
| Real DB learning cycle / actual SSE / empty-volume restart | Added in #30 | Deterministic generation/arithmetic; no external model claim |
| Third-party vulnerabilities | Partial mitigation in #31/#32/#34/#35/#36 | Six Python pins have a clean combined local audit; compatible Web/Taro fixes reduce findings. All remain unmerged; unresolved JS/image issues remain |
| Complete RAG upload→parse→embed→retrieve→citation pipeline | Controlled-embedding PGVector integration proposed in #33 | Actual URL parsing, chunking, vector storage/search and source metadata; real-provider quality and browser citation rendering remain unverified |
| Immutable Actions / credential-free checkout | Proposed and CI verified in #37 | 24 pinned calls, 13 runner checks; main still unmodified |
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

## Follow-up: HTTP framework security and compatibility

Before this follow-up, main remained `712c0538571d01129c0f8b1fb5488b35c9df6058`, #29–#33 remained open Drafts, and #29 was at `9ed5ff8f42d00e527bb2736a037138e2b4a542ef`. Its seven workflows passed, including [69/69 backend modules](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39811500513). This later pass does not erase the earlier observed grace-response race or merge #30's fix.

### Framework patch #34

Head: `59b8826c3b9c1222862386b2b35b9afbb6214e51`. FastAPI 0.115.12 → 0.141.1 and an explicit Starlette 1.3.1 security pin replace the vulnerable 0.46.2 resolution. sse-starlette remains 2.2.1 after compatibility tests. This is a bounded upgrade, not a claim to use the latest upstream releases.

New `tests.test_framework_transport` tests use the application's upload/chat routers and request-logging middleware. Two URL-encoded limit assertions reproduced the baseline failure (422 instead of 400). The patched environment passes these plus multipart text limits, file-byte/owner preservation beyond the spool threshold, and real loopback Uvicorn HTTP SSE completion and disconnect cleanup. The streaming test receives the synthetic answer while the generator still awaits its next item, then observes its `finally` cleanup after closing the HTTP response. Auth, ingest storage and chat output are controlled substitutes; no database, browser or external model is implied by these six tests.

Fresh Python 3.12.14 environments completed uncached installations before any tests/audits:

```bash
python3 -m venv /tmp/la-framework
/tmp/la-framework/bin/python -m pip install --no-cache-dir -r backend/requirements.txt
/tmp/la-framework/bin/python -m pip check
cd backend
/tmp/la-framework/bin/python -m unittest tests.test_framework_transport -v
# Existing modules were each run in a separate interpreter:
/tmp/la-framework/bin/python -m unittest tests.test_chat_api -v
/tmp/la-framework/bin/python -m unittest tests.test_upload_api -v
/tmp/la-framework/bin/python -m unittest tests.test_ingest_service -v
/tmp/la-framework/bin/python -m unittest tests.test_request_logging_middleware -v
```

Result: 67 tests passed (6 + 50 + 1 + 7 + 3). An initial middleware invocation used the nonexistent `tests.test_request_logging` name and failed import; the corrected command above passed. `tests.test_auth_api` skipped all 12 PostgreSQL tests locally without TEST_DATABASE_URL. No Docker/PostgreSQL local acceptance is claimed; the existing hosted workflows supply that evidence.

A separate fresh environment combined only the requirements edits in #31/#32/#34. The same framework/chat/middleware modules (59 tests), #32's upload-parser/ingest modules (14), and #31's HTTP-env/env-validation/MCP modules (30) passed in separate interpreters: **103 total**. The tests were run from their respective PR worktrees against that shared fresh dependency environment; this is not a merged code candidate or combined hosted CI.

```bash
# After the complete uncached installation of the six-pin combination:
python -m pip check
python -m pip freeze > /tmp/la-six-pin-resolved.txt
/tmp/la-audit-tools/bin/pip-audit --disable-pip --no-deps \
  -r /tmp/la-six-pin-resolved.txt -f json -o /tmp/la-six-pin-audit.json
```

Audit result: exit **0**, 97 distributions, no matched known vulnerabilities. The framework-only environment had 96 distributions and still exited **1** for four packages patched independently by #31/#32. [Normalized snapshots](DEPENDENCY_SECURITY_REVIEW.md) retain both results, duplicate-aware counts and requirements checksums. Dependency ranges, other languages, image packages, historical rights and live/staging gates remain open.

#34 hosted workflows at the head above: **all seven workflows passed**, verified in the subsequent follow-up. The full-suite job log confirms **70/70 modules** passed (including all six new tests), with fresh migrations and bootstrap. The previous in-progress API status has now resolved to success. Authentication separately passed 22 PostgreSQL regression tests and 18 real FastAPI-through-Next HTTP assertions. The latter are authentication checks; real SSE through Next remains the separate #30 scope.

| Workflow | Run |
| --- | --- |
| Backend full suite | [39814090305](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814090305) |
| Real authentication | [39814090451](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814090451) |
| Clean Compose | [39814090156](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814090156) |
| Quality | [39814090137](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814090137) |
| Next migration | [39814090113](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814090113) |
| Public data | [39814090229](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814090229) |
| Compose isolation | [39814090054](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814090054) |

Documentation checks: all 18 changed-file local Markdown links and both new audit JSON snapshots validated; 12 public-data/Compose/provenance tests and `git diff --check` passed. The release-gate command still exits 2: current questions 0, historical ledger 530 unresolved.

No changes were merged. Resolve requirements overlap without dropping reviewed pins, then repeat all workflow gates on the eventual combined candidate SHA. **Release remains NO-GO.**

## Follow-up: Web and Taro transitive dependencies

Main remained `712c0538571d01129c0f8b1fb5488b35c9df6058`; #29–#34 remained open Drafts. #34's previously pending backend run completed successfully. #29 at `66573e3c6bb7b191e50828c3a58dc82becb3de24` also passed all seven workflows, including [69/69 backend modules](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814959827), [quality](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814959822), [Next](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814959884), [auth](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814959867), [Compose](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814959826), [public data](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814959914) and [isolation](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39814959792). Earlier failures/skips remain documented above.

### Web patch #35

Head: `2238f3e6f67cda6966891dd961e78ad8ef3b7419`. Fresh worktree on main; Node 24.19.0 / npm 11.9.0, fresh npm cache and no existing node_modules or production build output:

```bash
cd frontend
npm audit --package-lock-only --json
npm update brace-expansion browserslist postcss-selector-parser --package-lock-only --ignore-scripts --no-audit
npm ci --cache <new-cache>
npm run test:css
npm run lint
npm run typecheck
NEXT_TELEMETRY_DISABLED=1 INTERNAL_API_BASE=http://127.0.0.1:18080/api npm run build
npm run smoke:proxy
npm audit --package-lock-only --json
npm audit --omit=dev --package-lock-only --json
```

All install/build/test commands passed. Lint retains 12 existing warnings. Three new CSS tests run real Tailwind/PostCSS/Autoprefixer against original temporary sources, using the project's theme/content globs; they verify custom/arbitrary utilities, responsive/hover/dark conditions and a fixed test browser prefix target. The proxy smoke uses a synthetic upstream/SSE, not a real model. The generated next-env.d.ts change was reverted in this newly created worktree; unrelated existing worktrees were untouched.

Full audit exits **1** before and after: 10 → 9 affected package nodes, 11 → 2 distinct direct advisory IDs. The after state has 7 high and 2 moderate affected nodes. New propagation to the already-present postcss-nested explains why the aggregate reduction differs from removed direct advisories. Production audit exits **0**, no findings. Seven locked versions change within existing ranges; direct framework versions remain unchanged. See the [snapshot and remaining chains](audits/web-transitives-2026-10-22.json).

All seven hosted workflows passed. The [Next job](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39817698550) log confirms all three CSS regressions and HTTP proxy smoke passed on Node 22; production Docker login and production advisory checks also passed. This is build/transport evidence, not browser visual acceptance.

### Taro patch #36

Head: `5c7b992ea290e342649783e5a27a1f31f60a43e2`. Independent fresh worktree/cache on the same main baseline:

```bash
cd frontend-weapp
npm audit --package-lock-only --json
npm update proxy-addr shell-quote websocket-driver vm2 --package-lock-only --ignore-scripts --no-audit
npm ci --cache <new-cache>
npm run typecheck
npm run lint
npm run test:chat-stream
npm run build:weapp
npm audit --package-lock-only --json
npm explain vm2 proxy-addr shell-quote websocket-driver --json
```

Install, typecheck, lint, existing stream-client tests and mini-program build passed. Only four locked package versions change; npm recalculates peer metadata for other entries without changing their versions. The existing stream test is now included in the Taro quality workflow. Both full audits exit **1**: affected package nodes 83 → 79, critical nodes 8 → 4, distinct direct advisory IDs 162 → 118. The remaining distribution is 4 critical / 51 high / 23 moderate / 1 low. See the [snapshot](audits/taro-transitives-2026-10-22.json). No claim is made that optional prerender/dev-server paths, live WeChat/device behavior or production bundle reachability have all been tested.

All seven hosted workflows passed at the #36 head above. The Taro job log confirms the existing stream-client regression and tourist build passed on Node 22. Both #35 and #36 backend logs confirm **69/69 modules** passed with disposable PostgreSQL. These completed runs are not evidence for a future combined candidate.

| Workflow | #35 | #36 |
| --- | --- | --- |
| Backend full suite | [39817697973](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39817697973) | [39818031199](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39818031199) |
| Authentication | [39817697993](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39817697993) | [39818031223](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39818031223) |
| Clean Compose | [39817698030](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39817698030) | [39818031170](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39818031170) |
| Quality | [39817698011](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39817698011) | [39818031355](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39818031355) |
| Next migration | [39817698550](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39817698550) | [39818031221](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39818031221) |
| Public data | [39817698028](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39817698028) | [39818031149](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39818031149) |
| Compose isolation | [39817698012](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39817698012) | [39818031166](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39818031166) |

Documentation follow-up: 17 local links and both new audit snapshots/counts validated; 12 public-data/Compose/provenance tests and `git diff --check` passed.

Both lockfiles were generated by npm and their Git blob hashes verified byte-for-byte before publication. No direct Dependabot major update, force audit fix, new production dependency, ignored audit failure, merge, release or live deployment was performed. Owner review, combined-candidate CI, unresolved dependencies, license/asset/history clearance and live/staging acceptance remain required. **NO-GO remains in effect.**

## Follow-up: CI supply chain and composition preflight — 2026-10-23

Main remains `712c0538571d01129c0f8b1fb5488b35c9df6058`. At the start of this
follow-up, 21 PRs were open, including Drafts #29–#36. #29 at
`c1b7ae3f8ffabf21b80375e17007f533d2ae530f` completed all seven workflows and 13
checks; its [backend log](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39818807513)
confirms 69/69 modules. Those are prior-head results, not this documentation update's CI.

### CI hardening #37

Head: `169baf1bc7e98c52858a4a6c83b27cacc770162f`. All 24 Action calls now use
full official commit SHAs, resolved independently through GitHub's refs API and
`git ls-remote`. Existing major versions remain. All 13 checkout steps disable
credential persistence and immediately check repository-local Git HTTP headers.
Three regressions use fresh temporary Git repositories and synthetic values;
they reject a persisted header without logging it and fail on inspection errors.

```bash
python -m unittest discover -s scripts/tests -p 'test_*.py' -v
python scripts/check_ci_checkout.py
/tmp/la-actionlint-1.7.12
# The binary above was fetched from the official release and its archive SHA-256
# checked against GitHub asset metadata before extraction/execution.
git diff --check
```

All 15 script tests and all seven workflow syntax/expression checks pass locally.
YAML inspection verified all 24 immutable references, 13 credential-free checkouts
with immediate checks, and existing read-only permissions. The Git tree uploaded
through GitHub matched the local tree byte-for-byte. No application dependency or
production behavior changes are included in #37.

All seven hosted workflows passed at this head, including **69/69 backend modules**.
The job-step results confirm the credential check passed in **all 13 jobs**, including
those whose default working directory is a client subdirectory. Actual runner
checkout/build compatibility is verified; global credential stores and malicious
PR isolation are outside this check's scope.

| Workflow | Run |
| --- | --- |
| Backend full suite | [39912718896](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39912718896) |
| Quality | [39912718895](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39912718895) |
| Clean Compose | [39912718819](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39912718819) |
| Public data | [39912718914](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39912718914) |
| Next verification | [39912718863](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39912718863) |
| Authentication | [39912718926](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39912718926) |
| Compose isolation | [39912718868](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39912718868) |

### Local combination preflight (not a released or hosted candidate)

The [machine-readable snapshot](audits/candidate-preflight-2026-10-23.json) records
the exact eight heads, application order and resulting Git tree. In a disposable
detached worktree on the baseline, each proposal's binary diff was applied with
`git apply --3way --index`, stopping on any error. #30 through #37 applied in order
without conflicts. No GitHub PR was merged, no candidate commit was created and
no combined branch was pushed.

The resulting tree is `cf0a8bde243191d7b6a6f14056e58fd16669e9dc`. It retains all
six Python security pins, both npm-generated lockfiles, the CSS/stream CI additions
and all Action pins/checkout checks. On this combined local tree:

```bash
/tmp/la-actionlint-1.7.12
python -m unittest discover -s scripts/tests -p 'test_*.py' -v
python -m unittest discover -s backend/tests -p test_architecture_boundaries.py -v
python -m compileall -q backend/app backend/tests backend/scripts scripts
git diff --cached --check
```

Results: **15 script + 9 architecture tests passed**, workflow lint, compilation
and whitespace checks passed. This preflight did **not** install the combined
runtime dependencies, run database tests, build clients or execute hosted CI.
Individual PR success cannot establish those combined outcomes. Repeat the full
existing workflows on the final reviewed candidate commit before release.

Main still lacks these unmerged fixes. Image digests/OS scanning, unresolved
JavaScript findings, content/license/history review and live-model/browser/device/
staging acceptance remain open. **Release remains NO-GO.**
