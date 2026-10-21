# Independently authored example questions

The [practice_questions.json](practice_questions.json) file contains two elementary, independently drafted questions about binary-tree preorder traversal. These demonstrate the supported JSON shape; they do not replace the unaudited 408 practice bank.

The current importer requires an initialized local PostgreSQL database with the canonical concept `data-structure.binary-tree.traversal` already present. After setting up a disposable development database and seeding the required concept metadata, you can validate the example **without inserting records**:

```bash
cd backend
python scripts/import_questions.py ../examples/practice_questions.json --dry-run
```

This `--dry-run` opens a database connection and may fail if the concept does not exist. Do not run against production. The main question bank remains excluded from the root Apache-2.0 grant pending a provenance review.
