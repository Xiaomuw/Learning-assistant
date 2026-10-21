# 408 Question Bank: Rights Review and Replacement Plan

**Status: public redistribution NOT cleared. No source-license conclusion has been reached.**

## Confirmed acquisition method

The project owner states the 530 questions were **collected through AI web searches of existing question banks, and subsequently organized**. This is not the same as independent creation from abstract educational concepts.

The former `main` snapshot of `data/practice_questions/all_408.json` had 530 rows across 53 concepts; four per-subject JSON mirrors matched it. [Draft PR #6](https://github.com/Xiaomuw/Learning-assistant/pull/6) removes all five files from its **proposed** current tree; `main` and old commits have not yet been changed. The JSON does **not** identify source websites, owners, reuse permissions, or prompt and tool histories. Exact text comparisons against the open web have not established the original rightsholders. No confirmed license should be inferred from discoverability or AI-assisted rewriting.

This is a provenance risk, **not a finding that any particular question is infringing**. Factual knowledge and terminology can be freely used; original expressive wording or compilation may carry separate rights depending on jurisdiction and circumstances.

## Maintainer decision: separate code from data

- Keep original application code and original docs under the proposed Apache-2.0 terms to the extent the project can lawfully license them.
- Treat all existing web-collected questions as **REVIEW_REQUIRED**. The code license does not grant redistribution rights to them.
- Keep the public sample questions in `examples/practice_questions.json`; those are separate, newly drafted examples.
- Provide JSON/CSV import tooling so authorized datasets may be deployed privately without adding them to a public Git tree.
- Do not present web-collected questions as "open source", "free to reuse", or "AI-original" while source rights are unverified.

## Immediate actions (before public release)

1. **Preserve evidence privately.** Keep your own existing question JSON and any search/prompt logs in private, access-controlled storage as needed for a legitimate provenance review. Do not post the question text again in public PRs or issues.
2. **Prevent additional public redistribution.** Check active deployments, archives, release artifacts and future build packages for bundled source material. Refrain from redistributing uncleared questions.
3. **Complete the reviewed public-tree cleanup.** [Draft PR #6](https://github.com/Xiaomuw/Learning-assistant/pull/6) proposes deleting the five JSON banks and replaces the fixed 530-question test with synthetic data. After explicit maintainer review, it must be merged **before** this stacked governance PR. Current `main` has not been changed.
4. **Protect working functionality.** Retain generic import APIs and schemas; replace tests that depend on a fixed licensed corpus with small synthetic fixtures, or use authorized private test data strictly outside the public repo.
5. **Evaluate history separately.** Deleting current files does not remove them from prior Git commits, forks or cached references. Coordinate any history rewrite with collaborators, and check GitHub's documentation and applicable policies before attempting it. Do not force-push as part of this draft PR.
6. **If seeking restoration:** determine source URLs, author/rightsholder, exact license, permission for redistribution/modification, attribution requirements and any evidence for each question or source set. Review individually where necessary.
7. **Only reintroduce cleared data.** Adopt a separate dataset license only for content the maintainer actually controls or has authority to license; preserve external content's original terms.

## Mechanical provenance inventory

`data/provenance/408-source-review.csv` contains **question IDs and status only**, not question wording. All 530 entries currently start as `REVIEW_REQUIRED` with acquisition method `AI_WEB_SEARCH_REORGANIZED`. No source URLs or permission are invented.

The standard-library-only tool now has **two modes**: while the old bank remains, it verifies canonical/mirror correspondence; after all five files disappear from the current tree, it verifies no partial/unexpected bank exists while preserving the 530-entry ledger as historical bookkeeping (not live question content):

```bash
python scripts/audit_question_bank_provenance.py --json

# Broader release gate (remains blocked for historical clearance, even after current-tree deletion):
python scripts/audit_question_bank_provenance.py --release-gate --json

# Unit tests for the checker use only synthetic data:
python -m unittest discover -s scripts/tests -p 'test_*.py' -v
```

Review columns: `question_id`, `acquisition_method`, `source_url`, `source_title`, `rights_holder`, `license_or_permission`, `evidence_ref`, `review_status`, `notes`.

Set `CLEARED` **only after human review**, with a valid permission basis and an evidence reference. Merely entering `CLEARED` cannot establish legal rights; the script checks bookkeeping, **not copyright law**. If a source cannot be cleared, use `REPLACE` or `REMOVE`, and remove that entry from the distributed corpus only after replacing/removing the actual underlying question.

## Next-step review and integration

[PR #6](https://github.com/Xiaomuw/Learning-assistant/pull/6) and this OSS-readiness PR are coordinated via [MERGE_SEQUENCE.md](MERGE_SEQUENCE.md). When both changes are combined, public CI should pass with no old question JSON; the source ledger must not be treated as an active corpus. A passing current-tree data check is **not** a statement that earlier forks/commits were erased or legally cleared.

## Out-of-scope decisions pending owner approval

Removing the 530 existing question records from `main`, altering deployed databases, deleting any private original copy, or rewriting Git history would have potentially disruptive effects. **None of these are performed by this documentation/validation PR.**

Related: [issue #5](https://github.com/Xiaomuw/Learning-assistant/issues/5), [license scope](../LICENSE-SCOPE.md), [release audit](DATA_AND_RELEASE_AUDIT.md).
