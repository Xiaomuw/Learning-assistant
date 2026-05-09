from __future__ import annotations

import importlib
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.schemas.contracts import UserMemoryRecord, UserProfileRecord
from app.shared.schemas.subject import DEFAULT_SUBJECTS
from tests.postgres_test_utils import TemporaryPostgresSchema


class RepositoryInitTest(unittest.TestCase):
    def test_latest_quiz_merge_appends_and_dedupes_without_database(self) -> None:
        os.environ.setdefault(
            "DATABASE_URL",
            "postgresql+psycopg://test:test@127.0.0.1:5432/learning_assistant_test",
        )
        session_repos = importlib.import_module("app.infrastructure.db.repositories.sessions")
        merged = session_repos._merge_latest_quiz_items(
            [
                {
                    "question_id": "ai-1",
                    "question": "栈的特点是什么？",
                    "options": [{"key": "A", "text": "先进后出"}],
                    "correct_option": "A",
                }
            ],
            [
                {
                    "question_id": "ai-1",
                    "question": "栈的特点是什么？",
                    "options": [{"key": "A", "text": "先进后出"}],
                    "correct_option": "A",
                },
                {
                    "question_id": "ai-2",
                    "question": "TCP 属于哪一层协议？",
                    "options": [{"key": "A", "text": "传输层"}],
                    "correct_option": "A",
                },
            ],
            existing_subject_id="data-structure",
            incoming_subject_id="computer-network",
        )

        self.assertEqual([item["question_id"] for item in merged], ["ai-1", "ai-2"])
        self.assertEqual(merged[0]["subject_id"], "data-structure")
        self.assertEqual(merged[0]["notebook_id"], "data-structure")
        self.assertEqual(merged[1]["subject_id"], "computer-network")
        self.assertEqual(merged[1]["notebook_id"], "computer-network")

    def test_database_init_and_core_crud(self) -> None:
        with TemporaryPostgresSchema() as db_schema:
            db_schema.configure_env()
            db_database = importlib.reload(importlib.import_module("app.infrastructure.db.database"))
            importlib.reload(importlib.import_module("app.infrastructure.db.models"))
            auth_repos = importlib.reload(importlib.import_module("app.infrastructure.db.repositories.auth"))
            bootstrap_repos = importlib.reload(importlib.import_module("app.infrastructure.db.repositories.bootstrap"))
            subjects_repos = importlib.reload(importlib.import_module("app.infrastructure.db.repositories.subjects"))
            users_repos = importlib.reload(importlib.import_module("app.infrastructure.db.repositories.users"))
            session_repos = importlib.reload(importlib.import_module("app.infrastructure.db.repositories.sessions"))
            practice_repos = importlib.reload(importlib.import_module("app.infrastructure.db.repositories.practice"))
            knowledge_stats_repos = importlib.reload(importlib.import_module("app.infrastructure.db.repositories.knowledge_stats"))
            settings_repos = importlib.reload(importlib.import_module("app.infrastructure.db.repositories.settings"))

            db_database.ensure_postgres_extensions()
            bootstrap_repos.init_database()

            subjects = [item.model_dump() for item in subjects_repos.list_subject_records()]
            self.assertGreaterEqual(len(subjects), len(DEFAULT_SUBJECTS))

            created = subjects_repos.create_subject_record("测试笔记本", "🧪", "用于单测的资料库").model_dump()
            self.assertEqual(created["name"], "测试笔记本")

            updated = subjects_repos.update_subject_record(
                created["id"],
                "测试笔记本-已更新",
                "📘",
                "更新后的简介",
            ).model_dump()
            self.assertEqual(updated["name"], "测试笔记本-已更新")

            saved_memory = users_repos.save_user_memory_record(
                "user_test",
                UserMemoryRecord.model_validate({
                    "weak_points": ["HTTP"],
                    "error_count": {"HTTP": 2},
                    "recent_topics": ["HTTP"],
                    "last_session": "sess-1",
                }),
            ).model_dump()
            self.assertEqual(saved_memory["error_count"]["HTTP"], 2)

            profile = users_repos.save_user_profile_record(
                "user_test",
                UserProfileRecord(
                    user_id="user_test",
                    display_name="测试用户",
                    agent_style_name="严格导师",
                    agent_style_prompt="回答时要先指出关键概念。",
                    onboarding_completed=True,
                ),
            ).model_dump()
            self.assertTrue(profile["onboarding_completed"])

            created_user = auth_repos.create_auth_user_record(
                email="repo-test@example.com",
                password_hash="hashed-password-for-tests",
                display_name="仓储用户",
            )
            self.assertEqual(created_user.email, "repo-test@example.com")
            self.assertEqual(auth_repos.get_user_auth_record_by_email("repo-test@example.com").id, created_user.id)

            refresh_row = auth_repos.save_refresh_token_record(
                user_id=created_user.id,
                token_jti="jti-test-1",
                token_hash="hash-value",
                expires_at=datetime.now(timezone.utc),
            ).model_dump()
            self.assertEqual(refresh_row["token_jti"], "jti-test-1")

            session = session_repos.append_chat_turn_record(
                user_id="user_test",
                session_id="session-1",
                subject_id=created["id"],
                title="测试会话",
                user_message={"role": "user", "content": "你好"},
                assistant_message={"role": "assistant", "content": "你好，我在。"},
                latest_quiz=[
                    {
                        "question_id": "ai-1",
                        "question": "HTTP 默认端口是？",
                        "options": [
                            {"key": "A", "text": "20"},
                            {"key": "B", "text": "53"},
                            {"key": "C", "text": "80"},
                            {"key": "D", "text": "443"},
                        ],
                        "correct_option": "C",
                        "explanation": "HTTP 默认端口是 80。",
                        "option_rationales": {
                            "A": "20 是 FTP 数据端口。",
                            "B": "53 是 DNS 常见端口。",
                            "C": "80 是 HTTP 默认端口。",
                            "D": "443 是 HTTPS 默认端口。",
                        },
                        "knowledge_point": "HTTP",
                        "difficulty": "基础",
                        "source_type": "ai_generated",
                        "source_name": "",
                        "source_year": None,
                    }
                ],
                session_memory={
                    "summary_text": "当前会话正在围绕 HTTP 学习。",
                    "active_topic": "HTTP",
                    "current_goal": "理解 HTTP 的基本概念",
                    "open_loops": ["继续追问缓存与连接管理"],
                    "resolved_points": ["已经解释了 HTTP 是应用层协议"],
                    "last_question_type": "concept",
                    "last_updated_at": "2026-04-15T00:00:00Z",
                },
            ).model_dump()
            self.assertEqual(session["id"], "session-1")
            latest_sessions = [item.model_dump() for item in session_repos.list_chat_session_records(user_id="user_test", limit=20)]
            self.assertEqual((latest_sessions[0]["latest_quiz"] or [])[0]["question"], "HTTP 默认端口是？")
            self.assertEqual(session["session_memory"]["active_topic"], "HTTP")

            updated_session = session_repos.append_chat_turn_record(
                user_id="user_test",
                session_id="session-1",
                subject_id="computer-network",
                title="继续出题",
                user_message={"role": "user", "content": "再出一道计算机网络题"},
                assistant_message={"role": "assistant", "content": "已追加练习题。"},
                latest_quiz=[
                    {
                        "question_id": "ai-1",
                        "question": "HTTP 默认端口是？",
                        "options": [
                            {"key": "A", "text": "20"},
                            {"key": "B", "text": "53"},
                            {"key": "C", "text": "80"},
                            {"key": "D", "text": "443"},
                        ],
                        "correct_option": "C",
                        "explanation": "HTTP 默认端口是 80。",
                        "option_rationales": {
                            "A": "20 是 FTP 数据端口。",
                            "B": "53 是 DNS 常见端口。",
                            "C": "80 是 HTTP 默认端口。",
                            "D": "443 是 HTTPS 默认端口。",
                        },
                        "knowledge_point": "HTTP",
                        "difficulty": "基础",
                        "source_type": "ai_generated",
                        "source_name": "",
                        "source_year": None,
                    },
                    {
                        "question_id": "ai-2",
                        "question": "DNS 主要用于完成什么任务？",
                        "options": [
                            {"key": "A", "text": "域名解析"},
                            {"key": "B", "text": "磁盘调度"},
                            {"key": "C", "text": "进程同步"},
                            {"key": "D", "text": "内存分页"},
                        ],
                        "correct_option": "A",
                        "explanation": "DNS 主要负责把域名解析为 IP 地址。",
                        "option_rationales": {
                            "A": "域名解析是 DNS 的核心职责。",
                            "B": "磁盘调度属于操作系统 I/O 管理。",
                            "C": "进程同步属于操作系统并发控制。",
                            "D": "内存分页属于存储管理。",
                        },
                        "knowledge_point": "DNS",
                        "difficulty": "基础",
                        "source_type": "ai_generated",
                        "source_name": "",
                        "source_year": None,
                    },
                ],
                session_memory=session["session_memory"],
            ).model_dump()
            merged_quiz = updated_session["latest_quiz"]
            self.assertEqual([item["question_id"] for item in merged_quiz], ["ai-1", "ai-2"])
            self.assertEqual(merged_quiz[0]["subject_id"], created["id"])
            self.assertEqual(merged_quiz[1]["subject_id"], "computer-network")

            imported_count = practice_repos.upsert_question_bank_item_records(
                [
                    {
                        "id": "q-http-2024-1",
                        "subject_id": created["id"],
                        "knowledge_point": "HTTP",
                        "question": "下面哪个端口通常用于 HTTPS？",
                        "options": [
                            {"key": "A", "text": "21"},
                            {"key": "B", "text": "25"},
                            {"key": "C", "text": "80"},
                            {"key": "D", "text": "443"},
                        ],
                        "correct_option": "D",
                        "explanation": "HTTPS 默认端口是 443。",
                        "option_rationales": {
                            "A": "21 常用于 FTP 控制连接。",
                            "B": "25 常用于 SMTP。",
                            "C": "80 是 HTTP 默认端口。",
                            "D": "443 是 HTTPS 默认端口。",
                        },
                        "source_name": "数据库期末真题",
                        "source_year": 2024,
                        "difficulty": "基础",
                        "tags": ["真题", "网络"],
                    }
                ]
            )
            self.assertEqual(imported_count, 1)
            recommendations = [
                item.model_dump()
                for item in practice_repos.list_practice_recommendation_records(
                    users_repos.get_user_memory_record("user_test"),
                    subject_id=created["id"],
                    limit=2,
                )
            ]
            self.assertGreaterEqual(len(recommendations), 1)
            self.assertEqual(recommendations[0]["correct_option"], "D")

            attempt = practice_repos.create_practice_attempt_record(
                user_id="user_test",
                session_id="session-1",
                subject_id=created["id"],
                question_id="q-http-2024-1",
                question_snapshot=recommendations[0],
                selected_option="D",
                is_correct=True,
                knowledge_point="HTTP",
                source_type="question_bank",
            ).model_dump()
            self.assertTrue(attempt["is_correct"])
            self.assertEqual(attempt["selected_option"], "D")

            exposure_stat = knowledge_stats_repos.record_knowledge_exposure(
                user_id="user_test",
                subject_id=created["id"],
                knowledge_point="HTTP",
            )
            self.assertIsNotNone(exposure_stat)
            attempt_stat = knowledge_stats_repos.record_knowledge_attempt(
                user_id="user_test",
                subject_id=created["id"],
                knowledge_point="HTTP",
                is_correct=True,
            )
            self.assertIsNotNone(attempt_stat)
            mastery_rows = knowledge_stats_repos.list_knowledge_mastery_records(
                user_id="user_test",
                subject_id=created["id"],
            )
            self.assertEqual(mastery_rows[0].knowledge_point, "HTTP")
            self.assertEqual(mastery_rows[0].attempt_count, 1)
            self.assertEqual(mastery_rows[0].correct_count, 1)

            settings_repos.set_app_setting_record("chat_model", "openai-gpt-oss-20b")
            self.assertEqual(settings_repos.get_app_setting_record("chat_model").value, "openai-gpt-oss-20b")

            self.assertEqual(db_database.current_database_backend(), "postgresql")


if __name__ == "__main__":
    unittest.main()
