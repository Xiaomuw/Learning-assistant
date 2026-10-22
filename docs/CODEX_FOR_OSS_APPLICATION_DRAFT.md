# Codex for Open Source — truthful application draft

**Current status (2026-10-22): DRAFT FOR OWNER REVIEW; NOT SUBMITTED.** This is a template for the actual maintainer to review and update, not an application, admission claim, or guarantee. The maintainer should review the evidence and disclose unresolved licensing/security work before deciding whether to apply. Our release NO-GO is a project decision, not an additional official eligibility rule.

Official application: https://openai.com/form/codex-for-oss/

## Official conditions checked on 2026-10-22

The [current official form](https://openai.com/form/codex-for-oss/) invites active maintainers of open-source projects with meaningful usage, broad adoption or clear importance to the ecosystem. It looks for maintenance signals such as reviewing PRs, triaging issues and managing releases. It does not state a universal minimum star count. Selected maintainers may receive six months of ChatGPT Pro; Codex Security access and API credits are assessed for qualifying needs. Review is rolling and selection is not guaranteed.

The form currently limits each of the three narrative answers below to 500 characters. API credits should support maintainer coding/review/release work; do not describe them as a subsidy for this application's end-user tutoring traffic. The owner must reconfirm the live form and program terms before submitting. No application was submitted here.

## Known fields

- **GitHub user:** `Xiaomuw`
- **Public repository URL:** https://github.com/Xiaomuw/Learning-assistant
- **Maintainer role:** Primary maintainer (the repository owner controls the project)
- **Account name / email:** enter the real applicant's own details directly on the official form; do not put private email in a public repository
- **OpenAI Organization ID:** use the applicant's real ID if requested on the official form; never invent or publish a private ID
- **Interest:** choose Codex Security and/or API credits only if genuinely useful to the project

## Draft response: Why does this repository qualify? (max 500 characters)

I maintain Learning-assistant, an early-stage AI learning project with reusable LangGraph QA, practice-generation and mastery workflows, FastAPI/PostgreSQL persistence, and Next.js/Taro clients. Maintenance includes data-boundary cleanup, dependency review, reproducible CI and regression tests that exposed a real question-persistence defect. Broad external adoption is not yet established; the value is a reusable learning-agent architecture under active improvement.

**Characters:** 469/500.

## Draft response: How will you use API credits? (max 500 characters)

Use credits for maintainer coding, review and release work: reproduce issues, improve graph and database integration tests, evaluate safe dependency upgrades, review pull requests and prepare accurate release notes. Use synthetic or explicitly licensed fixtures and never send secrets or private learner data to public CI. Credits would support project maintenance, not subsidize end-user tutoring requests.

**Characters:** 407/500.

## Draft response: Anything else we should know? (max 500 characters)

The project is early-stage, with no verified external adoption. Apache-2.0 covers the code; two independent examples replace the unverified question bank in current trees. Historical data rights, dependency findings and live-model/browser/staging acceptance remain open. Release materials explicitly say NO-GO. We do not claim download counts, external contributors, production readiness or a completed security audit.

**Characters:** 418/500.

## Evidence snapshot (2026-10-22, must refresh before submission)

- Public GitHub repo with owner/maintainer write access: **yes**.
- Stars: **0**; forks: **0**; published Releases: **0** according to a fresh GitHub API check on 2026-10-22. No verified external usage/download metrics were available; do **not** invent them.
- PR #6 merged: the five original question JSONs are absent from the current main tree; generic import and AI practice remain.
- PR #3 merged: Apache-2.0, license scope, English README, governance templates, Dependabot, CI and historical provenance ledger are on main.
- PR #7 merged: Next.js 16.4.2 / React 19.3.0 migration, Docker login-route smoke and real auth regression CI are on main.
- Remaining rights issues: PRs #23–#25 have cleaned the current heads of `mian`, `codex/docker-production-deploy`, and `codex/qa-408-flow-web-toggle`; all checked branch heads are now clear of question-bank JSON. Historical Git exposure, rights for any content in older commits, and external copies remain unresolved.
- PR #28 merged: development Compose ports bind to loopback; clean-clone stack smoke and health/login/anonymous-auth checks pass on the documented PR snapshot based on main. See the exact-SHA [verification ledger](RELEASE_VERIFICATION.md).
- PR #22 merged: Alembic expected-head verification is dynamic and isolated PostgreSQL tests pass.
- Draft PR #30 adds a real PostgreSQL graph round-trip regression and fixes the discovered question JSON corruption, extends actual HTTP SSE coverage and verifies empty-volume restart. Draft #31 narrows two Python dependency alerts with focused tests. These are proposed work, not merged or released changes.
- Draft #32 adds parser security updates and real multipart/PDF regressions; Draft #33 adds controlled-embedding PostgreSQL retrieval tests and fixes two reproduced mapping-isolation defects. Exact-head outcomes and test limitations are in the verification ledger; these are maintenance evidence, not adoption or release claims.
- Draft #34 adds a coordinated FastAPI/Starlette security update, reproduced form-limit regressions and actual loopback HTTP SSE disconnect cleanup. A fresh local combination of #31/#32/#34 requirements passes 103 focused tests and reports no known Python dependency vulnerabilities; this is scoped evidence, not a comprehensive audit or merged release.
- Next steps: assess historical exposure and third-party rights, complete real-model/browser/staging tests, publish an accurate version, and collect genuine third-party adoption/feedback. The project still has no published Release and no verified external adoption metrics.
- Drafts #35/#36 reduce compatible Web/Taro transitive dependency findings and extend existing CI with project CSS-pipeline and stream-client regressions. Both full JavaScript audits still fail; these proposed mitigations are maintenance evidence, not a completed security audit.

## Mandatory accuracy checks before using these draft answers

- [ ] Refresh the real repository license, release, usage and maintainer evidence (including any changed numbers).
- [ ] Verify public project content is lawful to redistribute, with original and third-party ownership review as appropriate.
- [ ] Do not claim a security review or deployment validation that has not been completed.
- [ ] Update the narrative with specific real external usage, reusable modules or dependent projects if evidence becomes available.
- [ ] Keep every free-text field within the form's actual limits; count characters again if text changes.
- [ ] Let the applicant choose their own contact info, interests and Organization ID, then submit only with their explicit decision.

The program considers ecosystem value, usage and active maintenance. The form states no minimum star threshold; acceptance still cannot be inferred from CI or an Apache license. Clear ecosystem importance and genuine external feedback remain unproven for this project.
