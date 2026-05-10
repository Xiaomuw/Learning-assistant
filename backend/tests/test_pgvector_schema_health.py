from __future__ import annotations

import sys
import unittest
import importlib
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

    def test_reconcile_scan_reports_vector_data_quality_issues(self) -> None:
        script = importlib.import_module("scripts.reconcile_pgvector_kb_chunks")

        def fake_rows(statement: str, _params):
            if "SELECT name" in statement:
                return [{"name": "learning_data-structure"}]
            if "COUNT(*) AS embedding_count" in statement:
                return [{"embedding_count": 2}]
            if "GROUP BY doc_type" in statement:
                return [{"doc_type": "question_bank", "count": 2}]
            if "COUNT(kb_chunk.id) AS kb_chunk_count" in statement:
                return [{"kb_chunk_count": 1}]
            if "HAVING COUNT(*) > 1" in statement:
                return []
            if "AND kb_chunk.id IS NULL" in statement:
                return [{"vector_id": "v1", "source_id": "pq-1", "doc_type": "question_bank"}]
            if "embeddings.id IS NULL" in statement:
                return []
            if "vector_dims" in statement:
                return [
                    {"embedding_dimension": 384, "embedding_provider": "", "embedding_model": "", "embedding_profile_version": "", "count": 1},
                    {"embedding_dimension": 1024, "embedding_provider": "", "embedding_model": "", "embedding_profile_version": "", "count": 1},
                ]
            if "custom_id IS NULL" in statement:
                return [{"id": "row-1", "vector_id": "v1", "source_id": "pq-1", "doc_type": "question_bank"}]
            if "doc_type' IS NULL" in statement:
                return [{"vector_id": "v2", "source_id": "pq-2"}]
            return []

        with (
            patch.object(script, "pgvector_tables_ready", return_value=True),
            patch.object(script, "_rows", side_effect=fake_rows),
            patch.object(script, "get_collection_prefix", return_value="learning"),
        ):
            result = script.scan(None, limit=10)

        self.assertTrue(result["pgvector_ready"])
        self.assertEqual(result["collection_count"], 1)
        self.assertEqual(result["embedding_count"], 2)
        self.assertEqual(result["kb_chunk_count"], 1)
        self.assertEqual(result["doc_type_counts"], {"question_bank": 2})
        self.assertFalse(result["is_empty_collection"])
        self.assertIn("missing_custom_id", result["issues"])
        self.assertIn("missing_doc_type", result["issues"])
        self.assertIn("mixed_embedding_dimensions", result["issues"])
        self.assertIn("vectors_without_kb_chunk", result["issues"])


if __name__ == "__main__":
    unittest.main()
