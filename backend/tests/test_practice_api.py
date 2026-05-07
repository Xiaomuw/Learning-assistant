from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.interfaces.auth.dependencies import require_current_user, verify_user_access
from app.interfaces.api.practice import router as practice_router
from app.shared.schemas.contracts import (
    AuthUserView,
    PracticePackResult,
    PracticeRecommendation,
    PracticeRecommendationsResult,
    PracticeSubmissionResult,
    QuizRequestResolution,
    UserMemoryRecord,
)


class PracticeApiTest(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(practice_router, prefix="/api")
        app.dependency_overrides[require_current_user] = lambda: AuthUserView(
            id="default_user",
            email="default@example.com",
            display_name="测试用户",
            status="active",
        )
        app.dependency_overrides[verify_user_access] = lambda: AuthUserView(
            id="default_user",
            email="default@example.com",
            display_name="测试用户",
            status="active",
        )
        self.client = TestClient(app)

    def test_recommendations_endpoint_returns_items(self) -> None:
        with patch(
            "app.interfaces.api.practice.get_recommendations",
            return_value=PracticeRecommendationsResult(
                subject_id="general",
                items=[
                    PracticeRecommendation(
                        question_id="bank-1",
                        question="数据库索引的主要作用是什么？",
                        options=[
                            {"key": "A", "text": "增加网络带宽"},
                            {"key": "B", "text": "加快查询速度"},
                            {"key": "C", "text": "自动备份数据"},
                            {"key": "D", "text": "减少磁盘容量"},
                        ],
                        correct_option="B",
                        explanation="索引主要用于加快查询。",
                        option_rationales={"B": "索引提升查询效率。"},
                        knowledge_point="数据库索引",
                        difficulty="基础",
                        source_type="question_bank",
                        source_name="数据库期末真题",
                        source_year=2024,
                    )
                ],
            ),
        ):
            response = self.client.get("/api/users/default_user/practice/recommendations")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["items"][0]["correct_option"], "B")

    def test_submit_practice_attempt_returns_feedback(self) -> None:
        with patch(
            "app.interfaces.api.practice.submit_attempt",
            return_value=PracticeSubmissionResult(
                is_correct=False,
                correct_option="C",
                explanation="HTTP 默认端口是 80。",
                option_rationales={
                    "A": "错误",
                    "B": "错误",
                    "C": "正确",
                    "D": "错误",
                },
                memory=UserMemoryRecord(
                    weak_points=["HTTP"],
                    error_count={"HTTP": 1},
                    recent_topics=["HTTP"],
                    last_session="session-1@2026-04-16T00:00:00Z",
                ),
                session_memory={
                    "summary_text": "当前会话正在围绕 HTTP 通过选择题查漏补缺。",
                },
            ),
        ):
            response = self.client.post(
                "/api/practice/attempts",
                json={
                    "user_id": "default_user",
                    "session_id": "session-1",
                    "subject_id": "general",
                    "quiz_item": {
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
                        "option_rationales": {"C": "正确"},
                        "knowledge_point": "HTTP",
                        "difficulty": "基础",
                        "source_type": "ai_generated",
                        "source_name": "",
                        "source_year": None,
                    },
                    "selected_option": "A",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["is_correct"])
        self.assertEqual(payload["selected_option"], "A")
        self.assertEqual(payload["correct_option"], "C")

    def test_submit_practice_attempt_returns_clear_error_message(self) -> None:
        with patch(
            "app.interfaces.api.practice.submit_attempt",
            side_effect=RuntimeError("value too long for type character varying(20)"),
        ):
            response = self.client.post(
                "/api/practice/attempts",
                json={
                    "user_id": "default_user",
                    "session_id": "session-1",
                    "subject_id": "general",
                    "quiz_item": {
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
                        "option_rationales": {"C": "正确"},
                        "knowledge_point": "HTTP",
                        "difficulty": "基础",
                        "source_type": "deterministic_adapter",
                        "source_name": "",
                        "source_year": None,
                    },
                    "selected_option": "A",
                },
            )

        self.assertEqual(response.status_code, 500)
        detail = response.json()["detail"]
        self.assertIn("提交作答失败", detail)
        self.assertIn("重新生成一组题包", detail)
        self.assertNotIn("character varying", detail)

    def test_create_practice_pack_uses_current_question_context(self) -> None:
        quiz_request = QuizRequestResolution(
            is_quiz_request=True,
            action="generate_practice_pack",
            intent="quiz_generation",
            topic="HashMap",
            source="current_question",
            target_module="practice",
        )
        with patch(
            "app.interfaces.api.practice.create_pack_from_request",
            return_value=PracticePackResult(
                subject_id="general",
                quiz_request=quiz_request,
                items=[
                    PracticeRecommendation(
                        question_id="ai-hashmap-1",
                        question="HashMap 为什么线程不安全？",
                        options=[
                            {"key": "A", "text": "因为它没有同步保护"},
                            {"key": "B", "text": "因为它只能存字符串"},
                            {"key": "C", "text": "因为它不能扩容"},
                            {"key": "D", "text": "因为它没有 key"},
                        ],
                        correct_option="A",
                        explanation="HashMap 非线程安全，多个线程同时修改可能破坏内部结构。",
                        option_rationales={"A": "正确"},
                        knowledge_point="HashMap",
                        difficulty="基础",
                    )
                ],
            ),
        ) as service:
            response = self.client.post(
                "/api/practice/packs",
                json={
                    "user_id": "default_user",
                    "session_id": "session-1",
                    "subject_id": "general",
                    "request_text": "AI补题",
                    "current_practice_question": {
                        "question": "HashMap 扩容机制是？",
                        "knowledge_point": "HashMap",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["quiz_request"]["topic"], "HashMap")
        self.assertEqual(payload["items"][0]["knowledge_point"], "HashMap")
        service.assert_called_once()


if __name__ == "__main__":
    unittest.main()
