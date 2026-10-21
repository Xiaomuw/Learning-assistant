# Practice-question data / 题库数据说明

**This public source tree intentionally contains no web-collected practice-question JSON.**

The project owner confirmed that the previous 530 questions were collected through AI-assisted searches of existing online question banks, then reorganized. Their original source licenses and redistribution permissions are not established. As a precaution, the proposed public tree removes the five former JSON files rather than declaring them original or broadly reusable.

**本仓库不再随代码附赠这批来源未核实的 530 道题**，但仍保留题库数据格式与导入程序。原有题目的来源、授权和历史传播问题需要另外处理；当前删除不代表已从 Git 历史或现有 Fork 中清除。

## How to use your own authorized dataset

- Small, newly drafted example: [examples/practice_questions.json](../../examples/practice_questions.json).
- Put legally permitted private data under the ignored `data/private/` (or another non-public directory); do not `git add -f` web-collected materials.
- Structured `practice_question` JSON import: `backend/scripts/import_questions.py` (requires an initialized local Postgres database and matching `kb_concept` IDs).
- General CSV/JSON/Excel question-bank import: `backend/scripts/import_question_bank.py`.
- For a quality audit, pass an explicit `--path` to `backend/scripts/audit_408_questions.py`.
- Data rebuild/cleanup is a **destructive maintenance operation**. `backend/scripts/rebuild_408_project_data.py` requires an explicit `--questions-path` and, in confirmed mode, `--import-questions`. Do not run cleanup against production or user data.

See [public data policy and safe testing notes](../../docs/PUBLIC_DATA_POLICY.md), [Apache license scope](../../LICENSE-SCOPE.md) and the [historical ID-only review ledger](../provenance/408-source-review.csv). The ledger is a review record, **not** a substitute for the removed JSON files.

## Rights and prior Git history

Removal from a draft branch does **not** erase older public commits, downloads, caches, forks or separately deployed databases. Do not claim full erasure or that legal status has been resolved. Treat any original corpus copies as unverified third-party material, preserve evidence in private storage only as lawfully appropriate, and assess history remediation separately.
