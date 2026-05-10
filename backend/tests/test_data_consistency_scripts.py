from __future__ import annotations

import importlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


audit_script = importlib.import_module("scripts.audit_data_consistency")
orphan_script = importlib.import_module("scripts.cleanup_orphan_user_data")
auth_history_script = importlib.import_module("scripts.cleanup_auth_history")


class DataConsistencyScriptsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        _create_schema(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_audit_reports_orphans_and_does_not_write(self) -> None:
        _seed_consistency_rows(self.engine)
        before = _count_rows(self.engine, "chat_sessions")

        report = audit_script.audit_data_consistency(self.engine, sample_limit=5)

        self.assertEqual(report["summary"]["status"], "issues_found")
        self.assertEqual(
            report["checks"]["user_references"]["chat_sessions.user_id"]["count"],
            1,
        )
        self.assertEqual(
            report["checks"]["graph_run_references"]["node_runs.graph_run_id"]["count"],
            1,
        )
        self.assertEqual(
            report["checks"]["canonical_concept_references"]["practice_question.concept_id"]["count"],
            1,
        )
        self.assertEqual(_count_rows(self.engine, "chat_sessions"), before)

    def test_orphan_cleanup_requires_confirm_token(self) -> None:
        _seed_consistency_rows(self.engine)

        dry_run = orphan_script.cleanup_orphan_user_data(self.engine, sample_limit=5)
        self.assertTrue(dry_run["dry_run"])
        self.assertGreaterEqual(dry_run["summary"]["planned_delete_count"], 4)
        self.assertEqual(_count_rows(self.engine, "graph_runs"), 2)
        self.assertEqual(_count_rows(self.engine, "node_runs"), 3)

        with self.assertRaises(ValueError):
            orphan_script.cleanup_orphan_user_data(self.engine, confirm="WRONG_TOKEN")

        executed = orphan_script.cleanup_orphan_user_data(
            self.engine,
            confirm=orphan_script.CONFIRM_TOKEN,
            sample_limit=5,
        )
        self.assertFalse(executed["dry_run"])
        self.assertGreaterEqual(executed["summary"]["deleted_count"], 4)
        self.assertEqual(_ids(self.engine, "graph_runs"), ["graph-valid"])
        self.assertEqual(_ids(self.engine, "node_runs"), ["node-valid"])
        self.assertEqual(_ids(self.engine, "chat_sessions"), ["chat-valid"])
        self.assertEqual(_ids(self.engine, "learning_events"), ["event-valid"])

    def test_auth_history_cleanup_requires_confirm_token_and_retains_recent_rows(self) -> None:
        now = datetime(2026, 5, 10, tzinfo=timezone.utc)
        _seed_auth_history_rows(self.engine, now)

        dry_run = auth_history_script.cleanup_auth_history(
            self.engine,
            retention_days=30,
            now=now,
        )
        self.assertTrue(dry_run["dry_run"])
        self.assertEqual(dry_run["summary"]["planned_delete_count"], 4)
        self.assertEqual(_count_rows(self.engine, "auth_refresh_tokens"), 4)

        with self.assertRaises(ValueError):
            auth_history_script.cleanup_auth_history(self.engine, confirm="WRONG_TOKEN")

        executed = auth_history_script.cleanup_auth_history(
            self.engine,
            confirm=auth_history_script.CONFIRM_TOKEN,
            retention_days=30,
            now=now,
        )
        self.assertFalse(executed["dry_run"])
        self.assertEqual(executed["summary"]["deleted_count"], 4)
        self.assertEqual(
            _ids(self.engine, "auth_refresh_tokens"),
            ["token-active", "token-recent-revoked"],
        )
        self.assertEqual(
            _ids(self.engine, "email_verification_challenges"),
            ["challenge-active", "challenge-recent-consumed"],
        )


def _create_schema(engine) -> None:
    ddl = (
        "CREATE TABLE users (id TEXT PRIMARY KEY)",
        "CREATE TABLE user_profiles (user_id TEXT PRIMARY KEY)",
        "CREATE TABLE user_memories (user_id TEXT PRIMARY KEY)",
        "CREATE TABLE auth_refresh_tokens (id TEXT PRIMARY KEY, user_id TEXT, token_jti TEXT, expires_at TIMESTAMP, revoked_at TIMESTAMP)",
        "CREATE TABLE email_verification_challenges (id TEXT PRIMARY KEY, email TEXT, expires_at TIMESTAMP, consumed_at TIMESTAMP)",
        "CREATE TABLE wechat_mini_identities (id TEXT PRIMARY KEY, user_id TEXT)",
        "CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, user_id TEXT, updated_at TIMESTAMP)",
        "CREATE TABLE practice_attempts (id TEXT PRIMARY KEY, user_id TEXT, concept_id TEXT, created_at TIMESTAMP)",
        "CREATE TABLE user_knowledge_stats (user_id TEXT, knowledge_point TEXT, concept_id TEXT)",
        "CREATE TABLE graph_runs (id TEXT PRIMARY KEY, user_id TEXT, created_at TIMESTAMP)",
        "CREATE TABLE node_runs (id TEXT PRIMARY KEY, graph_run_id TEXT)",
        "CREATE TABLE tool_runs (id TEXT PRIMARY KEY, graph_run_id TEXT)",
        "CREATE TABLE learning_events (id TEXT PRIMARY KEY, user_id TEXT, concept_id TEXT, graph_run_id TEXT)",
        "CREATE TABLE attempts (id TEXT PRIMARY KEY, user_id TEXT, concept_id TEXT, graph_run_id TEXT, created_at TIMESTAMP)",
        "CREATE TABLE mastery_snapshots (id TEXT PRIMARY KEY, user_id TEXT, concept_id TEXT, updated_at TIMESTAMP)",
        "CREATE TABLE question_items (id TEXT PRIMARY KEY, user_id TEXT, primary_concept_id TEXT, graph_run_id TEXT)",
        "CREATE TABLE kb_subject (subject_id TEXT PRIMARY KEY)",
        "CREATE TABLE kb_chapter (chapter_id TEXT PRIMARY KEY, subject_id TEXT)",
        "CREATE TABLE kb_topic (topic_id TEXT PRIMARY KEY, subject_id TEXT, chapter_id TEXT)",
        "CREATE TABLE kb_concept (concept_id TEXT PRIMARY KEY, subject_id TEXT, chapter_id TEXT, topic_id TEXT)",
        "CREATE TABLE practice_question (question_id TEXT PRIMARY KEY, subject_id TEXT, concept_id TEXT, difficulty TEXT)",
    )
    with engine.begin() as connection:
        for statement in ddl:
            connection.execute(text(statement))


def _seed_consistency_rows(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id) VALUES ('user-valid')"))
        connection.execute(text("INSERT INTO kb_subject (subject_id) VALUES ('subject-valid')"))
        connection.execute(
            text(
                "INSERT INTO kb_chapter (chapter_id, subject_id) "
                "VALUES ('chapter-valid', 'subject-valid')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO kb_topic (topic_id, subject_id, chapter_id) "
                "VALUES ('topic-valid', 'subject-valid', 'chapter-valid')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO kb_concept (concept_id, subject_id, chapter_id, topic_id) "
                "VALUES ('concept-valid', 'subject-valid', 'chapter-valid', 'topic-valid')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO practice_question (question_id, subject_id, concept_id, difficulty) "
                "VALUES "
                "('question-valid', 'subject-valid', 'concept-valid', 'medium'), "
                "('question-orphan-concept', 'subject-valid', 'concept-missing', 'medium')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO graph_runs (id, user_id) VALUES "
                "('graph-valid', 'user-valid'), "
                "('graph-orphan-user', 'user-missing')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO node_runs (id, graph_run_id) VALUES "
                "('node-valid', 'graph-valid'), "
                "('node-missing-graph', 'graph-missing'), "
                "('node-orphan-user-graph', 'graph-orphan-user')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO chat_sessions (id, user_id) VALUES "
                "('chat-valid', 'user-valid'), "
                "('chat-orphan-user', 'user-missing')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO learning_events (id, user_id, concept_id, graph_run_id) VALUES "
                "('event-valid', 'user-valid', 'concept-valid', 'graph-valid'), "
                "('event-orphan-user', 'user-missing', 'concept-missing', 'graph-valid')"
            )
        )


def _seed_auth_history_rows(engine, now: datetime) -> None:
    old = now - timedelta(days=45)
    recent = now - timedelta(days=5)
    future = now + timedelta(days=5)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO auth_refresh_tokens (id, user_id, token_jti, expires_at, revoked_at)
                VALUES
                  (:old_expired, 'user-valid', 'jti-old-expired', :old, NULL),
                  (:old_revoked, 'user-valid', 'jti-old-revoked', :future, :old),
                  (:recent_revoked, 'user-valid', 'jti-recent-revoked', :future, :recent),
                  (:active, 'user-valid', 'jti-active', :future, NULL)
                """
            ),
            {
                "old_expired": "token-old-expired",
                "old_revoked": "token-old-revoked",
                "recent_revoked": "token-recent-revoked",
                "active": "token-active",
                "old": old,
                "recent": recent,
                "future": future,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO email_verification_challenges (id, email, expires_at, consumed_at)
                VALUES
                  (:old_expired, 'old-expired@example.com', :old, NULL),
                  (:old_consumed, 'old-consumed@example.com', :future, :old),
                  (:recent_consumed, 'recent-consumed@example.com', :future, :recent),
                  (:active, 'active@example.com', :future, NULL)
                """
            ),
            {
                "old_expired": "challenge-old-expired",
                "old_consumed": "challenge-old-consumed",
                "recent_consumed": "challenge-recent-consumed",
                "active": "challenge-active",
                "old": old,
                "recent": recent,
                "future": future,
            },
        )


def _count_rows(engine, table_name: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0)


def _ids(engine, table_name: str) -> list[str]:
    id_column = "user_id" if table_name in {"user_profiles", "user_memories"} else "id"
    with engine.connect() as connection:
        return [
            str(row[0])
            for row in connection.execute(
                text(f"SELECT {id_column} FROM {table_name} ORDER BY {id_column}")
            ).all()
        ]


if __name__ == "__main__":
    unittest.main()
