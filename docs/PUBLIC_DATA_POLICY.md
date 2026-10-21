# Public dataset boundary and private import policy

## Status: review proposal; no changes to the default branch or deployments

This document accompanies a **draft pull request** that removes five tracked question-bank JSON files from the proposed public source tree. The owner confirmed the 530 questions were assembled using AI web searches of existing online question banks. Permission to redistribute the sources has **not** been established. This remediation is precautionary; it is not a declaration that any particular question infringes copyrights.

## What is removed

The proposal deletes current versions of these files (not their Git history):

- `data/practice_questions/all_408.json`
- `data/practice_questions/data_structure.json`
- `data/practice_questions/operating_system.json`
- `data/practice_questions/computer_network.json`
- `data/practice_questions/computer_organization.json`

No dataset is copied into another public path or attachment as part of this change. Deleting public files does not delete your private copy, earlier commits, forks, caches, user accounts or deployed database data.

## What remains

- FastAPI / LangGraph / RAG, learning events, practice-question generation and mastery processing
- The structured practice-question schema and database persistence
- Authorized data import via `backend/scripts/import_questions.py` for canonical practice-question JSON
- General CSV, JSON and Excel import via `backend/scripts/import_question_bank.py`
- The example file `examples/practice_questions.json`, containing two newly drafted elementary demonstration questions
- Existing built-in knowledge explanations written in Python source and optional curriculum imports. **These have not been subjected to a complete independent content-rights audit.** No claim of full legal clearance is made.

## Optional local workflow (isolated test environment only)

1. Obtain written permission or another valid lawful basis to **use and, if applicable, redistribute** the desired data. Online availability and AI paraphrasing alone do not grant permission.
2. Keep your authorized data in `data/private/` or another ignored, access-controlled local directory. Configure an isolated PostgreSQL database with PGVector and the required canonical concept IDs.
3. To validate structured JSON, run the following from `backend/` against an **isolated development database**. The importer initializes the database even in dry-run mode, so it is **not** an offline/no-write command:

```bash
python scripts/import_questions.py ../examples/practice_questions.json --dry-run
```

4. For your own authorized file, replace the path with its local location and choose `--on-conflict skip` or `--on-conflict upsert` when actually importing. Import can write to the database. Never test on production or user data.
5. For general CSV/JSON/Excel, use `python scripts/import_question_bank.py /path/to/approved-file.csv --subject data-structure`, again only against an isolated database you control.

## Destructive maintenance script

The `backend/scripts/rebuild_408_project_data.py` script is a **database cleanup/rebuild utility**, not an ordinary dataset loader. It now requires a supplied `--questions-path` for an import, and a confirmed rebuild additionally requires `--import-questions`. A default run without `--confirm` stays in dry-run mode. It may still inspect the local database. Only use this operation in disposable, backed-up environments with informed approval.

## What to do with the old public history

Because the old questions are already committed on `main`, merging a deletion only removes them from the new default tree. A separate, coordinated decision may be needed about Git history rewriting, forks, GitHub cached data, releases, external clones and any usage/distribution obligations. **Do not force-push or remove original private backups without a deliberate plan.** If necessary, obtain professional legal advice about removal, attribution and preservation obligations.

## Coordination with the other draft PR

[OSS readiness PR #3](https://github.com/Xiaomuw/Learning-assistant/pull/3) has been updated with dual-mode provenance checks: they distinguish the old corpus being present from its complete absence in the proposed current tree. The 530-ID ledger remains **historical review metadata**, not redistributed question text. Both draft PRs must still pass **combined** CI and receive final review before either is merged.

No deployment, release, merge or Git-history rewrite is performed by this draft proposal.
