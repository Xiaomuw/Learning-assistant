# Open-source Readiness Checklist

This checklist tracks readiness for sustainable public maintenance of **Learning-assistant**. It is not an OpenAI approval checklist and does not establish any eligibility or acceptance.

## 1. Intellectual-property and security review (release blockers)

- [ ] Establish ownership and the right to license original code and any copied snippets. Resolve existing contributors' or employers' rights if applicable.
- [x] Confirm collection method: AI web-searched existing question banks and reorganized results; this is **not** proof of distribution rights.
- [x] Merged [PR #6](https://github.com/Xiaomuw/Learning-assistant/pull/6): all five original JSON banks are absent from the current main tree; generic imports and AI-practice features remain. Historical commits and older branches are not cleaned by this merge.
- [ ] Resolve **remaining historical and active-branch exposure**: main is clean at its current tree, but codex/docker-production-deploy and codex/qa-408-flow-web-toggle still have five JSONs each, and mian has 42 JSON files not individually rights-audited. See [remediation plan](QUESTION_BANK_REMEDIATION.md) and [branch inventory](GIT_HISTORY_EXPOSURE_REVIEW.md).
- [ ] Audit third-party code, images, diagrams and UI assets; retain upstream attributions and licenses.
- [ ] Review direct and transitive dependency licenses and generate any required notices.
- [ ] Scan repository content and Git history for credentials, personal data, tokens, user documents and unsafe sample configuration. Revoke exposed secrets as needed.
- [ ] Review auth, upload, model tools and request isolation for security-sensitive behavior.
- [ ] Upgrade the affected Next.js 14.2.29 dependency and regression-test the web client ([issue #4](https://github.com/Xiaomuw/Learning-assistant/issues/4)).
- [ ] Review development Compose port exposure and default database credentials before network deployment.
- [ ] Complete [data and release audit](DATA_AND_RELEASE_AUDIT.md).

## 2. Repository foundation (proposed in the OSS-readiness PR)

- [x] Existing Chinese technical README, deployment docs, source structure and test scripts
- [x] Apache-2.0 root LICENSE and explicit LICENSE-SCOPE.md merged into main; scope excludes the unverified historical question corpus.
- [x] Proposed English `README.en.md`, contribution and governance guides
- [x] Proposed `SECURITY.md` and structured issue/PR templates
- [x] Proposed lightweight GitHub Actions CI checks (not a substitute for integration tests)
- [ ] Complete original-code, contributor, third-party asset and dependency-rights audit; adding Apache-2.0 does not clear unverified material.
- [x] Initial PR CI passed for commit `f1e5b66`: Python syntax, Next.js lint and Taro typecheck.
- [x] Expanded CI passed on commit `11a217b` ([workflow](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39600371744)): architecture tests, Next.js lint/build, Taro lint/type/build.
- [x] Dual-mode provenance-audit tests passed for corpus-present baseline on commit `ecf2488` ([workflow](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39608895451)).
- [x] Verified combined stacked CI: **5/5 jobs passed** on `5cc85ad` ([quality](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39609831876), [public-data/Postgres](https://github.com/Xiaomuw/Learning-assistant/actions/runs/39609831829)). Question corpus absent from combined tree; historical review still blocked.

## 3. Developer experience and adoption

- [ ] Add an architecture image and screenshots that contain no private information
- [x] Provide two newly drafted synthetic example questions (not a replacement for the 408 bank)
- [x] Add 530-ID provenance ledger and a structure/review-status audit (all 530 remain REVIEW_REQUIRED)
- [ ] Get the five unverified corpus JSON files off the public default branch after owner review/PR merge; [issue #5](https://github.com/Xiaomuw/Learning-assistant/issues/5) tracks their unresolved **historical** rights.
- [ ] Run the documented clean-room setup and record successful environment versions
- [ ] Eliminate the fresh-clone dependency on ignored `backend/storage/data/curriculum/` fixtures in some tests
- [ ] Provide a reproducible demo, clearly labeled if experimental
- [ ] Describe target developers, use cases and how this differs from existing LangGraph examples
- [ ] Set accurate repository description and topics using GitHub settings

Suggested repository description:
`Open-source AI learning assistant with LangGraph orchestration, RAG, practice generation, mastery tracking, Next.js and Taro clients.`

Suggested topics (only if they remain accurate):
`langgraph`, `langchain`, `rag`, `fastapi`, `pgvector`, `nextjs`, `taro`, `ai-learning`.

## PR ordering

See [MERGE_SEQUENCE.md](MERGE_SEQUENCE.md) for the completed merge sequence and remaining release gates. PRs #6, #3 and #7 are merged; no release, production deployment or history rewrite has been performed.

## 4. Versioning and maintenance

- [ ] Review and resolve or close obsolete pull requests (do not merge without review)
- [ ] Verify local backend, graph and frontend checks
- [ ] Run authenticated smoke tests and dedicated PostgreSQL integration tests against isolated test databases
- [ ] Publish changelog and an initial release **after** provenance/security review
- [ ] Triage genuine community issues and record decisions transparently
- [ ] Track genuine users, external contributors, reuse and adoption without manipulating metrics

## Security upgrade coordination

- [x] Merged [PR #7](https://github.com/Xiaomuw/Learning-assistant/pull/7): Next.js 16.4.2 / React 19.3.0, production Docker login-route smoke, dependency audit, and real auth regression workflow passed before merge.
- [ ] Complete real-model RAG/chat/SSE, browser/mobile acceptance, external email delivery, public TLS/CORS/proxy and staging checks. CI is not a full production acceptance test.
- [ ] Remove scoped React Hooks migration exceptions and review remaining lint warnings when safe ([issue #8](https://github.com/Xiaomuw/Learning-assistant/issues/8)); this is follow-up maintenance work.

## 5. OpenAI Codex for Open Source application

See [truthful application draft and evidence checklist](CODEX_FOR_OSS_APPLICATION_DRAFT.md). Once public licensing, project quality and true adoption are better established, apply through the official [Codex for Open Source form](https://openai.com/form/codex-for-oss/). The program looks at real maintenance, usage, and ecosystem relevance. Avoid representing synthetic metrics or a self-authored showcase as broad adoption.
