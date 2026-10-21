# Proposed review and merge sequence for Draft PR #6 and Draft PR #3

This document is a **plan**, not authorization to merge, rewrite history or deploy.

## Dependency relationship

1. [PR #6 — public data separation](https://github.com/Xiaomuw/Learning-assistant/pull/6) targets `main`. It proposes removal of five web-sourced question JSONs from the current tree while preserving generic learning/AI features and using newly drafted test fixtures.
2. [PR #3 — OSS readiness](https://github.com/Xiaomuw/Learning-assistant/pull/3) must be stacked **on top of PR #6** for review. It adds the Apache-2.0 proposal, maintenance policies, English README, historical 530-ID review ledger and **dual-mode** audit script that also works when all five JSONs are absent.
3. A combined CI run must verify both the proposed public-data-boundary workflow and the OSS quality workflow against the same tree.

## Non-negotiable checks before any merge

- [ ] The combined current tree includes **none** of the five removed JSON banks; the ID-only ledger is not question content.
- [ ] The importer/rebuild test suite passes against disposable PostgreSQL; release-ready status isn't inferred from CI alone.
- [ ] The dual-mode provenance audit in the combined tree reports `retired_from_current_tree`, `canonical_questions: 0`, `ledger_rows: 530`, `current_tree_data_boundary_passes: true`, **`release_gate_passes: false`** while historical rights remain unknown.
- [ ] Review README and license scope so neither suggests the old question text is now licensed, or history has been erased.
- [ ] Inspect PR #3 diff **against PR #6**, then obtain human approval for each merge separately.
- [ ] Recheck both PR heads, their base refs and CI after any later edits.

## After owner review (not executed automatically)

First merge PR #6 into `main`, then **retarget PR #3 from the temporary PR #6 branch to `main`** after confirming a clean diff and successful checks. Merge PR #3 only when its copyright and configuration review has been approved.

Next address [historical and other-branch exposure](GIT_HISTORY_EXPOSURE_REVIEW.md), including `mian` and older `codex/` branches that still carry question JSONs, the remaining [dataset-rights issue](https://github.com/Xiaomuw/Learning-assistant/issues/5), and the [Next.js security upgrade](https://github.com/Xiaomuw/Learning-assistant/issues/4). Do not tag a public release while material release blockers remain.

Nothing in this plan constitutes a completed legal determination, external-security audit or a version release.
