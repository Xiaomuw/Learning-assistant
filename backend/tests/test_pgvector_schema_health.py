from __future__ import annotations

import sys
import unittest
import os
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.services.rag import vector_store


class PgvectorSchemaHealthTest(unittest.TestCase):
    def test_schema_health_reports_missing_custom_id_and_indexes(self) -> None:
        with (
            patch("app.services.rag.vector_store.pgvector_tables_ready", return_value=True),
            patch(
                "app.services.rag.vector_store._embedding_table_columns",
                return_value={"collection_id", "embedding", "document", "cmetadata"},
            ),
            patch("app.services.rag.vector_store._embedding_table_indexes", return_value={"ix_cmetadata_gin"}),
        ):
            health = vector_store._pgvector_schema_health()

        self.assertTrue(health["schema_ready"])
        self.assertFalse(health["index_ready"])
        self.assertIn("missing_custom_id", health["schema_issues"])
        self.assertIn("pgvector_indexes_incomplete", health["schema_issues"])

    def test_schema_health_ready_after_pgvector_hardening_indexes_exist(self) -> None:
        with (
            patch("app.services.rag.vector_store.pgvector_tables_ready", return_value=True),
            patch(
                "app.services.rag.vector_store._embedding_table_columns",
                return_value={"collection_id", "embedding", "document", "cmetadata", "custom_id"},
            ),
            patch(
                "app.services.rag.vector_store._embedding_table_indexes",
                return_value={
                    "ix_langchain_pg_embedding_custom_id",
                    "ix_langchain_pg_embedding_cmetadata_gin",
                },
            ),
        ):
            health = vector_store._pgvector_schema_health()

        self.assertTrue(health["schema_ready"])
        self.assertTrue(health["index_ready"])
        self.assertEqual(health["schema_issues"], [])


if __name__ == "__main__":
    unittest.main()
