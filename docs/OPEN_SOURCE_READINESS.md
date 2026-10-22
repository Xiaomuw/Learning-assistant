# Open-source Readiness Checklist

This checklist tracks readiness for sustainable public maintenance of **Learning-assistant**. It is not an OpenAI approval checklist and does not establish any eligibility or acceptance.

**Release decision: NO-GO.** See [current verification ledger](RELEASE_VERIFICATION.md), [candidate runbook](RELEASE_CANDIDATE.md), and [dependency/security evidence](DEPENDENCY_SECURITY_REVIEW.md). Checked items below are scoped observations, not full release clearance.

## 1. Intellectual-property and security review (release blockers)

- [ ] Establish ownership and the right to license original code and any copied snippets. Resolve existing contributors' or employers' rights if applicable.
- [x] Confirm collection method: AI web-searched existing question banks and reorganized results; this is **not** proof of distribution rights.
- [x] Merged [PR #6](https://github.com/Xiaomuw/Learning-assistant/pull/6): all five original JSON banks are absent from the current main tree; generic imports and AI-practice features remain. Historical commits and older branches are not cleaned by this merge.
- [x] Merged [PR #23](https://github.com/Xiaomuw/Learning-assistant/pull/23), [PR #24](https://github.com/Xiaomuw/Learning-assistant/pull/24) and [PR #25](https://github.com/Xiaomuw/Learning-assistant/pull/25): the current heads of mian and both older codex branches now contain no question-bank JSON files.
- [ ] Resolve **historical Git exposure**: old commits may still contain the web-collected corpus; no history rewrite or external-copy cleanup has been performed. See [remediation plan](QUESTION_BANK_REMEDIATION.md) and [branch inventory](GIT_HISTORY_EXPOSURE_REVIEW.md).
- [ ] Audit third-party code, images, diagrams and UI assets; retain upstream attributions and licenses.
- [ ] Review direct and transitive dependency licenses and generate any required notices.
- [x] Run authorized read-only current-tree and reachable-history secret scans; [scope and candidate findings](DEPENDENCY_SECURITY_REVIEW.md) recorded.
- [ ] Complete candidate triage, image/personal-data review and owner verification of historical test credential non-reuse; rotate any confirmed live credentials through the owner.
- [ ] Review auth, upload, model tools and request isolation for security-sensitive behavior.
- [x] Merged [PR #7](https://github.com/Xiaomuw/Learning-assistant/pull/7): upgraded to Next.js 16.4.2 / React 19.3.0 and passed migration CI.
- [x] Merged [PR #28](https://github.com/Xiaomuw/Learning-assistant/pull/28): development Compose ports bind to `127.0.0.1`; configuration guard and clean-clone smoke pass.
- [ ] Complete real-model RAG/chat/SSE, browser/mobile acceptance, external email delivery, TLS/CORS/proxy and staging checks ([issue #4](https://github.com/Xiaomuw/Learning-assistant/issues/4)).
- [x] Development Compose host ports bind only to loopback after PR #28; never reuse predictable development database credentials in production.
- [ ] Review production `.env` secret generation, reverse proxy/TLS/CORS and firewall rules before staging.
- [ ] Complete [data and release audit](DATA_AND_RELEASE_AUDIT.md).

## 2. Repository foundation

- [x] Existing Chinese technical README, deployment docs, source structure and test scripts
- [x] Apache-2.0 root LICENSE and explicit LICENSE-SCOPE.md merged into main; scope excludes the unverified historical question corpus.
- [x] English `README.en.md`, contribution and governance guides
- [x] `SECURITY.md` and structured issue/PR templates
- [x] Initial lightweight GitHub Actions CI checks (not a substitute for integration tests)
- [ ] Complete original-code, contributor, third-party asset and dependency-rights audit; adding Apache-2.0 does not clear unverified material.
- [x] Initial PR CI passed for commit `f1e5b66`: Python syntax, Next.js lint and Taro typecheck.
- [x] Expanded CI passed on commit `11a217b` ([workflow](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39600371744)): architecture tests, Next.js lint/build, Taro lint/type/build.
- [x] Dual-mode provenance-audit tests passed for corpus-present baseline on commit `ecf2488` ([workflow](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39608895451)).
- [x] Verified combined stacked CI: **5/5 jobs passed** on `5cc85ad` ([quality](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39609831876), [public-data/Postgres](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39609831829)). Question corpus absent from combined tree; historical review still blocked.

## 3. Developer experience and adoption

- [x] Add code-based Mermaid architecture diagrams in both READMEs.
- [ ] Capture current UI screenshots/video only after manual acceptance and privacy review; none fabricated.
- [x] Provide two newly drafted synthetic example questions (not a replacement for the 408 bank)
- [x] Add 530-ID provenance ledger and a structure/review-status audit (all 530 remain REVIEW_REQUIRED)
- [x] Current heads of checked branches have no question-bank JSON; historical commits and external copies remain unresolved ([history review](GIT_HISTORY_EXPOSURE_REVIEW.md)).
- [x] Clean-clone Docker Compose smoke passes on the baseline-based PR snapshot ([workflow](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39742007304)): builds and boots a disposable stack, checks backend `/health`, frontend `/login`, anonymous auth rejection and loopback bindings.
- [x] Record tested environment versions and exact-scoped results in the [verification ledger](RELEASE_VERIFICATION.md).
- [ ] Run human-operated staging acceptance with owner-approved secrets and external integrations.
- [x] `test_builtin_notebook_seed.py` creates its own synthetic curriculum in a temporary directory; fresh-clone CI passes. Private curriculum content is still absent from the public runtime.
- [x] Document an experimental keyless installation/synthetic-data runbook.
- [ ] Complete live-model/browser demo acceptance; do not treat the keyless health checks as a full AI demo.
- [x] English README explains target developers, reusable workflow boundaries and limitations.
- [ ] Set accurate repository description and topics using GitHub settings

Suggested repository description:
`Open-source AI learning assistant with LangGraph orchestration, RAG, practice generation, mastery tracking, Next.js and Taro clients.`

Suggested topics (only if they remain accurate):
`langgraph`, `langchain`, `rag`, `fastapi`, `pgvector`, `nextjs`, `taro`, `ai-learning`.

## PR ordering

See [MERGE_SEQUENCE.md](MERGE_SEQUENCE.md) for the completed merge sequence and remaining release gates. PRs #6, #3 and #7 are merged; no release, production deployment or history rewrite has been performed.

## 4. Versioning and maintenance

- [ ] Review and resolve or close obsolete pull requests (do not merge without review)
- [x] Baseline-main backend full suite passes ([workflow](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39709334122)).
- [x] Baseline-main frontend/mini-program quality checks pass ([workflow](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39709334030)).
- [x] Real authentication regression and isolated PostgreSQL workflow passes on the baseline-based PR snapshot ([workflow](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39742007279)).
- [ ] Verify real-model RAG/SSE, external email delivery and browser/mobile UX in staging.
- [ ] Publish changelog and an initial release **after** provenance/security review
- [ ] Triage genuine community issues and record decisions transparently
- [ ] Track genuine users, external contributors, reuse and adoption without manipulating metrics

## Security upgrade coordination

- [x] Merged [PR #7](https://github.com/Xiaomuw/Learning-assistant/pull/7): Next.js 16.4.2 / React 19.3.0, production Docker login-route smoke, dependency audit, and real auth regression workflow passed before merge.
- [ ] Complete real-model RAG/chat/SSE, browser/mobile acceptance, external email delivery, public TLS/CORS/proxy and staging checks. CI is not a full production acceptance test.
- [ ] Remove scoped React Hooks migration exceptions and review remaining lint warnings when safe ([issue #8](https://github.com/Xiaomuw/Learning-assistant/issues/8)).

## 5. OpenAI Codex for Open Source application

See [truthful application draft and evidence checklist](CODEX_FOR_OSS_APPLICATION_DRAFT.md). Once public licensing, project quality and true adoption are better established, apply through the official [Codex for Open Source form](https://openai.com/form/codex-for-oss/). The program looks at real maintenance, usage, and ecosystem relevance. Avoid representing synthetic metrics or a self-authored showcase as broad adoption.
