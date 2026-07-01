# 408 Practice Question Data

This directory contains the committed 408 practice question source data.

## Files

- `all_408.json` is the authoritative import file used by backend scripts and tests.
- `data_structure.json`, `operating_system.json`, `computer_network.json`, and `computer_organization.json` are exact subject-level mirrors of `all_408.json`.

## Maintenance

- Keep `all_408.json` as the source of truth for bulk import and rebuild flows.
- Keep the subject files synchronized with `all_408.json` when the question bank changes.
- Do not commit generated review artifacts here or in the repository root, including files such as `b15r.json`, `408_review_result.json`, `preview.json`, or temporary merge/filter scripts.
- Use `backend/scripts/audit_408_questions.py` for future question quality audits.
