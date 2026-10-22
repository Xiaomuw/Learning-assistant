# Codex for Open Source — truthful application draft

**Current status (2026-10-22): NOT YET READY FOR SUBMISSION.** This is a template for the actual maintainer to review and update, not an application, admission claim, or guarantee. Do not submit until the listed evidence and licensing/security blockers have been reviewed.

Official application: https://openai.com/form/codex-for-oss/

## Known fields

- **GitHub user:** `Xiaomuw`
- **Public repository URL:** https://github.com/Xiaomuw/Learning-assistant
- **Maintainer role:** Primary maintainer (the repository owner controls the project)
- **Account name / email:** enter the real applicant's own details directly on the official form; do not put private email in a public repository
- **OpenAI Organization ID:** use the applicant's real ID if requested on the official form; never invent or publish a private ID
- **Interest:** choose Codex Security and/or API credits only if genuinely useful to the project

## Draft response: Why does this repository qualify? (max 500 characters)

I am the primary maintainer of Learning-assistant, an early-stage AI learning assistant with reusable LangGraph workflows for RAG-based tutoring, practice generation, and mastery tracking. It provides FastAPI, Next.js and Taro clients with documented architecture and CI. The project is actively maintained but has not yet demonstrated broad external adoption; we aim to make these learning-agent patterns reproducible for developers.

**Characters:** 434/500.

## Draft response: How will you use API credits? (max 500 characters)

Use Codex/API credits for maintaining LangGraph workflow tests and evaluations, reviewing pull requests, triaging reproducible issues, upgrading dependencies safely, generating release notes, and supporting integration adapters. All testing would use synthetic or properly licensed datasets and avoid sending user secrets or copyrighted teaching content to public CI.

**Characters:** 367/500.

## Draft response: Anything else we should know? (max 500 characters)

This is an early-stage public project. The main branch now excludes the unverified question-bank JSON and provides independent examples, and the Apache-2.0 code license is in place. Older branches and Git history still need review, and real-model, browser and staging acceptance remain incomplete. No broad adoption, downloads, or external contributors are claimed.

**Characters:** 291/500.

## Evidence snapshot (2026-10-22, must refresh before submission)

- Public GitHub repo with owner/maintainer write access: **yes**.
- Stars: **0**; forks: **0**; published Releases: **0** according to the verified public repository snapshot. No verified external usage/download metrics were available; do **not** invent them.
- PR #6 merged: the five original question JSONs are absent from the current main tree; generic import and AI practice remain.
- PR #3 merged: Apache-2.0, license scope, English README, governance templates, Dependabot, CI and historical provenance ledger are on main.
- PR #7 merged: Next.js 16.4.2 / React 19.3.0 migration, Docker login-route smoke and real auth regression CI are on main.
- Remaining rights issues: PRs #23–#25 have cleaned the current heads of `mian`, `codex/docker-production-deploy`, and `codex/qa-408-flow-web-toggle`; all checked branch heads are now clear of question-bank JSON. Historical Git exposure, rights for any content in older commits, and external copies remain unresolved.
- Next steps: assess historical exposure and third-party rights, complete real-model/browser/staging tests, publish an accurate version, and collect genuine third-party adoption/feedback. The Alembic-head fix was merged as PR #22 after all four CI workflows passed.

## Mandatory accuracy checks before using these draft answers

- [ ] Refresh the real repository license, release, usage and maintainer evidence (including any changed numbers).
- [ ] Verify public project content is lawful to redistribute, with original and third-party ownership review as appropriate.
- [ ] Do not claim a security review or deployment validation that has not been completed.
- [ ] Update the narrative with specific real external usage, reusable modules or dependent projects if evidence becomes available.
- [ ] Keep every free-text field within the form's actual limits; count characters again if text changes.
- [ ] Let the applicant choose their own contact info, interests and Organization ID, then submit only with their explicit decision.

The program considers ecosystem value, usage and active maintenance. A 0-Star project is not automatically excluded, but acceptance cannot be assumed from CI or having an Apache license.
