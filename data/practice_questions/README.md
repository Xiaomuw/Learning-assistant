# 408 Practice Question Data

This directory contains the committed 408 practice question source data.

## Files

- `all_408.json` is the authoritative import file used by backend scripts and tests. A backend test expects 530 questions across 53 concepts, but this count does not establish rights.
- `data_structure.json`, `operating_system.json`, `computer_network.json`, and `computer_organization.json` are exact subject-level mirrors of `all_408.json`.

## Maintenance

- Keep `all_408.json` as the source of truth for bulk import and rebuild flows.
- Keep the subject files synchronized with `all_408.json` when the question bank changes.
- Do not commit generated review artifacts here or in the repository root, including files such as `b15r.json`, `408_review_result.json`, `preview.json`, or temporary merge/filter scripts.
- Use `backend/scripts/audit_408_questions.py` for future question quality audits.

## Licensing and provenance — pending review

The owner has confirmed that AI performed **web searches of existing online question banks and reorganized the results** into the committed practice data. Exact source URLs, authorship and redistribution permissions have **not** been established. These files are **explicitly excluded** from the project's root Apache-2.0 license grant. Do not assume this project's code license permits copying, remixing, or redistributing the question bank.

Before bundling this dataset with releases or reusing it elsewhere, the maintainer must document legitimate sources and permissions for each dataset (and for third-party questions as necessary), or replace/remove material for which redistribution cannot be justified. Merely marking data as excluded does not cure any existing public distribution rights issue. See [LICENSE-SCOPE.md](../../LICENSE-SCOPE.md), the [530-ID source-review ledger](../provenance/408-source-review.csv), the [remediation plan](../../docs/QUESTION_BANK_REMEDIATION.md) and the [release audit](../../docs/DATA_AND_RELEASE_AUDIT.md).

**中文提醒：**用户已确认 AI 联网搜索现有题库后整理成 530 道题，原始网址及再分发权限尚不明确；根目录 Apache-2.0 许可证**不授权**这些题库。若缺乏公开分发权利，应依法移除、替换或取得授权，不能把本说明当成合法分发证明。
