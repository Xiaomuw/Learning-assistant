from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _alembic_command() -> list[str]:
    local_alembic = BACKEND_ROOT / ".venv313" / "bin" / "alembic"
    if local_alembic.exists():
        return [str(local_alembic)]
    return [sys.executable, "-m", "alembic"]


class GraphMigrationContractTest(unittest.TestCase):
    def test_alembic_baseline_files_exist_for_graph_facts(self) -> None:
        self.assertTrue((BACKEND_ROOT / "alembic.ini").exists())
        self.assertTrue((BACKEND_ROOT / "alembic" / "env.py").exists())
        revision = BACKEND_ROOT / "alembic" / "versions" / "0001_graph_facts.py"
        self.assertTrue(revision.exists())

        content = revision.read_text(encoding="utf-8")
        for table_name in (
            "graph_runs",
            "node_runs",
            "tool_runs",
            "learning_events",
            "attempts",
            "mastery_snapshots",
            "question_items",
            "concepts",
        ):
            self.assertIn(table_name, content)
        self.assertIn("langsmith_run_id", content)
        self.assertIn("sampled", content)

    def test_alembic_wechat_mini_identity_migration_exists(self) -> None:
        revision = BACKEND_ROOT / "alembic" / "versions" / "0002_wechat_mini_identities.py"
        self.assertTrue(revision.exists())
        content = revision.read_text(encoding="utf-8")
        self.assertIn("wechat_mini_identities", content)
        self.assertIn("openid", content)
        self.assertIn("unionid", content)

    def test_alembic_knowledge_taxonomy_migration_exists(self) -> None:
        revision = BACKEND_ROOT / "alembic" / "versions" / "0003_knowledge_taxonomy.py"
        self.assertTrue(revision.exists())
        content = revision.read_text(encoding="utf-8")
        for table_name in ("kb_subject", "kb_chapter", "kb_topic", "kb_concept", "kb_chunk"):
            self.assertIn(table_name, content)
        for column_name in ("concept_id", "concept_name", "concept_mapping_status"):
            self.assertIn(column_name, content)

    def test_alembic_practice_question_migration_exists(self) -> None:
        revision = BACKEND_ROOT / "alembic" / "versions" / "0004_practice_question_import.py"
        self.assertTrue(revision.exists())
        content = revision.read_text(encoding="utf-8")
        self.assertIn("practice_question", content)
        for column_name in ("question_id", "concept_id", "options_json", "knowledge_points_json"):
            self.assertIn(column_name, content)

    def test_alembic_pgvector_hardening_migration_exists(self) -> None:
        revision = BACKEND_ROOT / "alembic" / "versions" / "0005_pgvector_infra_hardening.py"
        self.assertTrue(revision.exists())
        content = revision.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0005_pgvector_infra_hardening"', content)
        self.assertIn('down_revision: str | None = "0004_practice_question_import"', content)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", content)
        self.assertIn('bind.dialect.name != "postgresql"', content)
        self.assertIn("langchain_pg_collection", content)
        self.assertIn("langchain_pg_embedding", content)
        self.assertIn("custom_id", content)
        for index_name in (
            "ix_langchain_pg_collection_name",
            "ix_langchain_pg_embedding_collection_id",
            "ix_langchain_pg_embedding_custom_id",
            "uq_langchain_pg_embedding_collection_custom_id",
            "ix_langchain_pg_embedding_cmetadata_gin",
            "ix_langchain_pg_embedding_cmetadata_source_id",
            "ix_langchain_pg_embedding_cmetadata_doc_type",
            "ix_langchain_pg_embedding_cmetadata_concept_id",
            "ix_langchain_pg_embedding_cmetadata_topic_id",
        ):
            self.assertIn(index_name, content)
        self.assertIn("USING gin ((cmetadata::jsonb))", content)
        self.assertIn("cmetadata::jsonb ->>", content)
        for metadata_key in ("source_id", "doc_type", "concept_id", "topic_id"):
            self.assertIn(f'"{metadata_key}"', content)

    def test_alembic_auth_core_tables_migration_exists(self) -> None:
        revision = BACKEND_ROOT / "alembic" / "versions" / "0006_auth_core_tables.py"
        self.assertTrue(revision.exists())
        content = revision.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0006_auth_core_tables"', content)
        self.assertIn('down_revision: str | None = "0005_pgvector_infra_hardening"', content)
        for table_name in (
            "users",
            "user_profiles",
            "user_memories",
            "auth_refresh_tokens",
            "email_verification_challenges",
        ):
            self.assertIn(table_name, content)
        for index_name in (
            "ix_users_email",
            "ix_auth_refresh_tokens_user_id",
            "ix_auth_refresh_tokens_token_jti",
            "idx_email_verification_challenges_email_purpose_active",
        ):
            self.assertIn(index_name, content)

    def test_alembic_graph_migration_list_includes_auth_core_tables(self) -> None:
        revision_files = {
            path.name
            for path in (BACKEND_ROOT / "alembic" / "versions").glob("[0-9][0-9][0-9][0-9]_*.py")
        }
        self.assertTrue(
            {
                "0001_graph_facts.py",
                "0002_wechat_mini_identities.py",
                "0003_knowledge_taxonomy.py",
                "0004_practice_question_import.py",
                "0005_pgvector_infra_hardening.py",
                "0006_auth_core_tables.py",
                "0007_learning_event_idempotency.py",
                "0008_core_data_integrity.py",
                "0009_pgvector_core_tables.py",
                "0010_readiness_required_indexes.py",
            }.issubset(revision_files)
        )

    def test_alembic_learning_event_idempotency_migration_exists(self) -> None:
        revision = BACKEND_ROOT / "alembic" / "versions" / "0007_learning_event_idempotency.py"
        self.assertTrue(revision.exists())
        content = revision.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0007_learning_event_idempotency"', content)
        self.assertIn('down_revision: str | None = "0006_auth_core_tables"', content)
        self.assertIn("hash_key", content)
        self.assertIn("ix_learning_events_hash_key", content)
        self.assertIn("uq_learning_events_hash_key", content)

    def test_alembic_core_data_integrity_migration_exists(self) -> None:
        revision = BACKEND_ROOT / "alembic" / "versions" / "0008_core_data_integrity.py"
        self.assertTrue(revision.exists())
        content = revision.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0008_core_data_integrity"', content)
        self.assertIn('down_revision: str | None = "0007_learning_event_idempotency"', content)
        self.assertIn("postgresql_not_valid=True", content)
        self.assertIn("bind.dialect.name != \"postgresql\"", content)
        self.assertIn("fk_practice_question_concept_kb_concept", content)
        self.assertIn('"practice_question"', content)
        self.assertIn('"kb_concept"', content)
        self.assertNotIn("fk_practice_question_concept_concepts", content)
        self.assertNotIn("fk_question_items_user", content)
        self.assertNotIn("fk_node_runs_graph_run", content)

    def test_alembic_pgvector_core_tables_migration_exists(self) -> None:
        revision = BACKEND_ROOT / "alembic" / "versions" / "0009_pgvector_core_tables.py"
        self.assertTrue(revision.exists())
        content = revision.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0009_pgvector_core_tables"', content)
        self.assertIn('down_revision: str | None = "0008_core_data_integrity"', content)
        self.assertIn("CREATE TABLE langchain_pg_collection", content)
        self.assertIn("CREATE TABLE langchain_pg_embedding", content)
        self.assertIn("embedding vector", content)
        self.assertIn("custom_id TEXT", content)
        self.assertIn("ix_langchain_pg_embedding_cmetadata_gin", content)
        self.assertIn("is_empty_collection", (BACKEND_ROOT / "scripts" / "reconcile_pgvector_kb_chunks.py").read_text(encoding="utf-8"))

    def test_alembic_readiness_required_indexes_migration_exists(self) -> None:
        revision = BACKEND_ROOT / "alembic" / "versions" / "0010_readiness_required_indexes.py"
        self.assertTrue(revision.exists())
        content = revision.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0010_readiness_required_indexes"', content)
        self.assertIn('down_revision: str | None = "0009_pgvector_core_tables"', content)
        for index_name in (
            "ix_learning_events_user_id",
            "idx_learning_events_user_created",
            "ix_question_items_subject_id",
            "ix_question_items_primary_concept_id",
        ):
            self.assertIn(index_name, content)

    def test_alembic_upgrade_head_on_empty_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "graph_facts.db"
            env = os.environ.copy()
            env["ALEMBIC_DATABASE_URL"] = f"sqlite:///{db_path}"
            result = subprocess.run(
                [*_alembic_command(), "-c", "alembic.ini", "upgrade", "head"],
                cwd=BACKEND_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

            connection = sqlite3.connect(db_path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "select name from sqlite_master where type='table'"
                    ).fetchall()
                }
                table_columns = {
                    table_name: {
                        row[1]
                        for row in connection.execute(f"pragma table_info({table_name})").fetchall()
                    }
                    for table_name in table_names
                }
                table_indexes = {
                    table_name: {
                        row[1]
                        for row in connection.execute(f"pragma index_list({table_name})").fetchall()
                    }
                    for table_name in table_names
                }
                applied_revision = connection.execute(
                    "select version_num from alembic_version"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(applied_revision, "0010_readiness_required_indexes")
            self.assertTrue(
                {
                    "users",
                    "user_profiles",
                    "user_memories",
                    "auth_refresh_tokens",
                    "email_verification_challenges",
                    "graph_runs",
                    "node_runs",
                    "tool_runs",
                    "learning_events",
                    "attempts",
                    "mastery_snapshots",
                    "question_items",
                    "concepts",
                    "wechat_mini_identities",
                    "kb_subject",
                    "kb_chapter",
                    "kb_topic",
                    "kb_concept",
                    "kb_chunk",
                    "practice_question",
                    "alembic_version",
                }.issubset(table_names)
            )
            expected_columns = {
                "wechat_mini_identities": {
                    "id",
                    "user_id",
                    "openid",
                    "unionid",
                    "created_at",
                    "updated_at",
                    "last_login_at",
                },
                "kb_subject": {
                    "subject_id",
                    "subject_name",
                    "metadata_json",
                    "created_at",
                    "updated_at",
                },
                "kb_chapter": {
                    "chapter_id",
                    "subject_id",
                    "chapter_name",
                    "sort_order",
                    "metadata_json",
                    "created_at",
                    "updated_at",
                },
                "kb_topic": {
                    "topic_id",
                    "subject_id",
                    "chapter_id",
                    "topic_name",
                    "sort_order",
                    "metadata_json",
                    "created_at",
                    "updated_at",
                },
                "kb_concept": {
                    "concept_id",
                    "subject_id",
                    "chapter_id",
                    "topic_id",
                    "concept_name",
                    "aliases_json",
                    "prerequisites_json",
                    "importance",
                    "exam_frequency",
                    "question_types_json",
                    "metadata_json",
                    "created_at",
                    "updated_at",
                },
                "kb_chunk": {
                    "id",
                    "vector_id",
                    "subject_id",
                    "subject_name",
                    "chapter_id",
                    "chapter_name",
                    "topic_id",
                    "topic_name",
                    "concept_id",
                    "concept_name",
                    "source_file",
                    "page_start",
                    "page_end",
                    "mapping_status",
                    "content_hash",
                    "content_text",
                    "metadata_json",
                    "created_at",
                    "updated_at",
                },
                "practice_question": {
                    "question_id",
                    "subject_id",
                    "subject_name",
                    "chapter_name",
                    "topic_name",
                    "concept_id",
                    "concept_name",
                    "difficulty",
                    "stem",
                    "options_json",
                    "answer",
                    "explanation",
                    "knowledge_points_json",
                    "common_trap",
                    "metadata_json",
                    "source_file",
                    "created_at",
                    "updated_at",
                },
                "learning_events": {
                    "id",
                    "event_type",
                    "user_id",
                    "concept_id",
                    "graph_run_id",
                    "hash_key",
                    "payload",
                    "created_at",
                },
                "users": {
                    "id",
                    "email",
                    "password_hash",
                    "status",
                    "created_at",
                    "updated_at",
                    "last_login_at",
                },
                "user_profiles": {
                    "user_id",
                    "display_name",
                    "agent_style_name",
                    "agent_style_prompt",
                    "onboarding_completed",
                    "updated_at",
                },
                "user_memories": {
                    "user_id",
                    "weak_points",
                    "error_count",
                    "recent_topics",
                    "last_session",
                    "updated_at",
                },
                "auth_refresh_tokens": {
                    "id",
                    "user_id",
                    "token_jti",
                    "token_hash",
                    "expires_at",
                    "revoked_at",
                    "created_at",
                    "last_used_at",
                },
                "email_verification_challenges": {
                    "id",
                    "email",
                    "purpose",
                    "code_hash",
                    "expires_at",
                    "attempt_count",
                    "max_attempts",
                    "verified_at",
                    "consumed_at",
                    "last_sent_at",
                    "created_at",
                    "updated_at",
                },
            }
            for table_name, columns in expected_columns.items():
                self.assertTrue(columns.issubset(table_columns[table_name]), table_name)

            expected_indexes = {
                "users": {
                    "ix_users_email",
                },
                "auth_refresh_tokens": {
                    "ix_auth_refresh_tokens_user_id",
                    "ix_auth_refresh_tokens_token_jti",
                    "idx_auth_refresh_tokens_user_expires",
                    "idx_auth_refresh_tokens_revoked_expires",
                },
                "email_verification_challenges": {
                    "ix_email_verification_challenges_email",
                    "ix_email_verification_challenges_purpose",
                    "idx_email_verification_challenges_email_purpose_active",
                    "idx_email_verification_challenges_cleanup",
                },
                "wechat_mini_identities": {
                    "ix_wechat_mini_identities_user_id",
                    "ix_wechat_mini_identities_openid",
                    "ix_wechat_mini_identities_unionid",
                },
                "kb_chunk": {
                    "ix_kb_chunk_vector_id",
                    "ix_kb_chunk_subject_id",
                    "ix_kb_chunk_source_file",
                    "ix_kb_chunk_mapping_status",
                    "idx_kb_chunk_subject_concept",
                    "idx_kb_chunk_source_status",
                },
                "kb_concept": {
                    "ix_kb_concept_subject_id",
                    "ix_kb_concept_chapter_id",
                    "ix_kb_concept_topic_id",
                    "ix_kb_concept_concept_name",
                    "idx_kb_concept_subject_chapter_topic",
                },
                "practice_question": {
                    "ix_practice_question_concept_id",
                    "ix_practice_question_subject_id",
                    "ix_practice_question_difficulty",
                    "idx_practice_question_subject_concept",
                    "idx_practice_question_concept_difficulty",
                },
                "graph_runs": {
                    "idx_graph_runs_user_created",
                },
                "learning_events": {
                    "ix_learning_events_hash_key",
                    "ix_learning_events_user_id",
                    "uq_learning_events_hash_key",
                    "idx_learning_events_user_created",
                    "idx_learning_events_user_graph_run",
                },
                "question_items": {
                    "ix_question_items_subject_id",
                    "ix_question_items_primary_concept_id",
                    "idx_question_items_user_concept",
                },
            }
            for table_name, indexes in expected_indexes.items():
                self.assertTrue(indexes.issubset(table_indexes[table_name]), table_name)


if __name__ == "__main__":
    unittest.main()
