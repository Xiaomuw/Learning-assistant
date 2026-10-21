# Open-source Readiness Checklist

This checklist tracks readiness for sustainable public maintenance of **Learning-assistant**. It is not an OpenAI approval checklist and does not establish any eligibility or acceptance.

## 1. Intellectual-property and security review (release blockers)

- [ ] Establish ownership and the right to license original code and any copied snippets. Resolve existing contributors' or employers' rights if applicable.
- [ ] Trace the source and redistribution permission of **every bundled 408 practice-question dataset**. Remove or replace any data without adequate permissions; `LICENSE-SCOPE.md` alone does not cure existing publication.
- [ ] Audit third-party code, images, diagrams and UI assets; retain upstream attributions and licenses.
- [ ] Review direct and transitive dependency licenses and generate any required notices.
- [ ] Scan repository content and Git history for credentials, personal data, tokens, user documents and unsafe sample configuration. Revoke exposed secrets as needed.
- [ ] Review auth, upload, model tools and request isolation for security-sensitive behavior.
- [ ] Review development Compose port exposure and default database credentials before network deployment.
- [ ] Complete [data and release audit](DATA_AND_RELEASE_AUDIT.md).

## 2. Repository foundation (proposed in the OSS-readiness PR)

- [x] Existing Chinese technical README, deployment docs, source structure and test scripts
- [x] Proposed Apache-2.0 root `LICENSE` and explicit `LICENSE-SCOPE.md`
- [x] Proposed English `README.en.md`, contribution and governance guides
- [x] Proposed `SECURITY.md` and structured issue/PR templates
- [x] Proposed lightweight GitHub Actions CI checks (not a substitute for integration tests)
- [ ] Confirm the copyright audit before merging the license proposal into `main`
- [x] Initial PR CI passed for commit `f1e5b66`: Python syntax, Next.js lint and Taro typecheck.
- [ ] Verify expanded CI checks after the follow-up commit

## 3. Developer experience and adoption

- [ ] Add an architecture image and screenshots that contain no private information
- [x] Provide two newly drafted synthetic example questions (not a replacement for the 408 bank)
- [ ] Resolve permission or replace unaudited question-bank material
- [ ] Run the documented clean-room setup and record successful environment versions
- [ ] Eliminate the fresh-clone dependency on ignored `backend/storage/data/curriculum/` fixtures in some tests
- [ ] Provide a reproducible demo, clearly labeled if experimental
- [ ] Describe target developers, use cases and how this differs from existing LangGraph examples
- [ ] Set accurate repository description and topics using GitHub settings

Suggested repository description:
`Open-source AI learning assistant with LangGraph orchestration, RAG, practice generation, mastery tracking, Next.js and Taro clients.`

Suggested topics (only if they remain accurate):
`langgraph`, `langchain`, `rag`, `fastapi`, `pgvector`, `nextjs`, `taro`, `ai-learning`.

## 4. Versioning and maintenance

- [ ] Review and resolve or close obsolete pull requests (do not merge without review)
- [ ] Verify local backend, graph and frontend checks
- [ ] Run authenticated smoke tests and dedicated PostgreSQL integration tests against isolated test databases
- [ ] Publish changelog and an initial release **after** provenance/security review
- [ ] Triage genuine community issues and record decisions transparently
- [ ] Track genuine users, external contributors, reuse and adoption without manipulating metrics

## 5. OpenAI Codex for Open Source application

Once public licensing, project quality and true adoption are better established, apply through the official [Codex for Open Source form](https://openai.com/form/codex-for-oss/). The program looks at real maintenance, usage, and ecosystem relevance. Avoid representing synthetic metrics or a self-authored showcase as broad adoption.
