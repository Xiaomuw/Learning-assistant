# Codex for Open Source — truthful application draft

**Current status (2026-10-21): NOT YET READY FOR SUBMISSION.** This is a template for the actual maintainer to review and update, not an application, admission claim, or guarantee. Do not submit until the listed evidence and licensing/security blockers have been reviewed.

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

This is an early-stage public project. We are reviewing license ownership and historical dataset provenance, replacing unverified third-party question banks with independent examples, and validating security and deployment. No broad adoption, downloads, or external contributors are claimed.

**Characters:** 291/500.

## Evidence snapshot (2026-10-21, must refresh before submission)

- Public GitHub repo with owner/maintainer write access: **yes**.
- Stars: **0**; forks: **0**; published Releases: **0** according to the verified public repository snapshot. No verified external usage/download metrics were available; do **not** invent them.
- Draft PR #6: public data removal and authorization-independent synthetic test corpus; **not merged**.
- Draft PR #3: Apache-2.0 proposal, English README, governance templates, CI and historical provenance ledger; **not merged**.
- Draft PR #7: patched Next.js migration; verified CI/Docker tests; **not merged**.
- Remaining rights issues: old `main`, `mian` and two old `codex/` branches contain web-collected question JSON; historical exposure is not cleared.
- Next steps: approve/merge reviewed safe changes, resolve historical rights, test a clean deployment and end-user flows, publish an accurate version, and collect genuine third-party adoption/feedback.

## Mandatory accuracy checks before using these draft answers

- [ ] Refresh the real repository license, release, usage and maintainer evidence (including any changed numbers).
- [ ] Verify public project content is lawful to redistribute, with original and third-party ownership review as appropriate.
- [ ] Do not claim a security review or deployment validation that has not been completed.
- [ ] Update the narrative with specific real external usage, reusable modules or dependent projects if evidence becomes available.
- [ ] Keep every free-text field within the form's actual limits; count characters again if text changes.
- [ ] Let the applicant choose their own contact info, interests and Organization ID, then submit only with their explicit decision.

The program considers ecosystem value, usage and active maintenance. A 0-Star project is not automatically excluded, but acceptance cannot be assumed from CI or having an Apache license.
