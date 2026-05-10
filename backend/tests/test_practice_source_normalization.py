from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.chat.orchestrator_runtime import (
    _quiz_items_from_child_payload,
    _stream_chunk_from_orchestrator_update,
)
from app.application.practice.graph_facts import update_graph_mastery_from_practice_attempt
from app.domains.practice.attempts import record_practice_attempt_and_update_memory
from app.domains.practice.common import normalize_practice_source_type, normalize_quiz_item
from app.shared.schemas.contracts import MasteryEvaluationResult, PracticeRecommendation


class PracticeSourceNormalizationTest(unittest.TestCase):
    def test_internal_generation_source_maps_to_ai_generated_for_chat_quiz_items(self) -> None:
        items = _quiz_items_from_child_payload(
            {
                "question_items": [
                    {
                        "id": "q1",
                        "stem": "HTTP 默认端口是？",
                        "options": [
                            {"key": "A", "text": "20"},
                            {"key": "B", "text": "53"},
                            {"key": "C", "text": "80"},
                            {"key": "D", "text": "443"},
                        ],
                        "primary_concept_id": "HTTP",
                        "difficulty": "基础",
                        "generation_source": "deterministic_adapter",
                        "answer_key": {
                            "correct_option": "C",
                            "explanation": "HTTP 默认端口是 80。",
                            "option_rationales": {"C": "80 是 HTTP 默认端口。"},
                        },
                    }
                ]
            }
        )

        self.assertEqual(items[0]["source_type"], "ai_generated")
        self.assertEqual(items[0]["source_name"], "QuestionGenerationGraph")

    def test_stream_chunk_maps_question_generation_quiz_output(self) -> None:
        final_response = {
            "answer": "已围绕「stack」生成并保存 1 道基础单选题。",
            "source_level": "model",
            "concepts": [{"concept_id": "stack", "name": "stack", "confidence": 0.8, "source": "test"}],
            "ui_payload": {"target_graph_type": "question_generation"},
        }
        graph_state = {
            "source_policy": "open_tools",
            "intent_decision": {"intent": "generate_question"},
            "final_response": final_response,
            "child_graph_output": {
                "target_graph_type": "question_generation",
                "payload": {
                    "final_response": final_response,
                    "question_items": [
                        {
                            "id": "q1",
                            "stem": "栈这种数据结构最典型的访问规则是什么？",
                            "options": [
                                {"key": "A", "text": "先进先出"},
                                {"key": "B", "text": "后进先出"},
                                {"key": "C", "text": "按优先级先出"},
                                {"key": "D", "text": "随机访问任意位置"},
                            ],
                            "primary_concept_id": "stack",
                            "difficulty": "基础",
                            "answer_key": {
                                "correct_option": "B",
                                "explanation": "栈是 LIFO 后进先出。",
                                "option_rationales": {"B": "后进先出是栈。"},
                            },
                        }
                    ],
                    "generation_status": {"quality_passed": True},
                },
            },
        }

        chunk = _stream_chunk_from_orchestrator_update(
            node_name="response_composer",
            node_update={"final_response": final_response},
            graph_state=graph_state,
            initial_state={"question": "Generate one stack practice question"},
            request_mode="sync",
            latency_ms=120,
        )

        self.assertIsNotNone(chunk)
        self.assertEqual(chunk["node"], "quiz_output_node")
        self.assertEqual(chunk["state_update"]["quiz_items"][0]["knowledge_point"], "stack")
        self.assertTrue(chunk["state_update"]["quiz_generation_status"]["quality_passed"])

    def test_normalize_quiz_item_keeps_source_type_compatible_with_attempt_table(self) -> None:
        item = normalize_quiz_item(
            {
                "question_id": "q1",
                "question": "HTTP 默认端口是？",
                "options": [
                    {"key": "A", "text": "20"},
                    {"key": "B", "text": "53"},
                    {"key": "C", "text": "80"},
                    {"key": "D", "text": "443"},
                ],
                "correct_option": "C",
                "explanation": "HTTP 默认端口是 80。",
                "option_rationales": {"C": "80 是 HTTP 默认端口。"},
                "knowledge_point": "HTTP",
                "source_type": "deterministic_adapter",
            }
        )

        self.assertEqual(item.source_type, "ai_generated")
        self.assertEqual(normalize_practice_source_type("question_bank"), "question_bank")

    def test_submit_attempt_normalizes_internal_source_before_persisting(self) -> None:
        captured: dict[str, str] = {}

        def fake_create_attempt(**kwargs):
            captured.update(kwargs)
            return kwargs

        with (
            patch(
                "app.domains.practice.attempts.evaluate_practice_answer",
                return_value=MasteryEvaluationResult(
                    subject_id="general",
                    knowledge_point="HTTP",
                    normalized_answer="C",
                    is_correct=True,
                    score=100,
                    mastery_score=100,
                    mastery_level="mastered",
                    feedback="回答正确。",
                ),
            ),
            patch("app.domains.practice.attempts._create_practice_attempt", side_effect=fake_create_attempt),
            patch(
                "app.domains.practice.attempts._get_user_memory",
                return_value={"weak_points": [], "error_count": {}, "recent_topics": []},
            ),
            patch(
                "app.domains.practice.attempts._save_user_memory",
                return_value={"weak_points": [], "error_count": {}, "recent_topics": ["HTTP"], "last_session": ""},
            ),
        ):
            record_practice_attempt_and_update_memory(
                user_id="u1",
                session_id="",
                subject_id="general",
                quiz_item=PracticeRecommendation(
                    question_id="q1",
                    question="HTTP 默认端口是？",
                    options=[
                        {"key": "A", "text": "20"},
                        {"key": "B", "text": "53"},
                        {"key": "C", "text": "80"},
                        {"key": "D", "text": "443"},
                    ],
                    correct_option="C",
                    explanation="HTTP 默认端口是 80。",
                    option_rationales={"C": "80 是 HTTP 默认端口。"},
                    knowledge_point="HTTP",
                    source_type="deterministic_adapter",
                ),
                selected_option="C",
            )

        self.assertEqual(captured["source_type"], "ai_generated")

    def test_submit_attempt_updates_graph_mastery_for_canonical_concept(self) -> None:
        graph_attempt_payloads: list[dict] = []
        graph_states: list[dict] = []

        class FakeAttemptRepository:
            def create_attempt(self, payload: dict) -> str:
                graph_attempt_payloads.append(dict(payload))
                return str(payload["id"])

        class FakeRepos:
            attempts = FakeAttemptRepository()
            learning_events = object()
            mastery_snapshots = object()

        class FakeCompiledGraph:
            def invoke(self, state: dict) -> dict:
                graph_states.append(dict(state))
                return {}

        class FakeGraph:
            def compile(self) -> FakeCompiledGraph:
                return FakeCompiledGraph()

        with (
            patch(
                "app.domains.practice.attempts.evaluate_practice_answer",
                return_value=MasteryEvaluationResult(
                    subject_id="computer-network",
                    knowledge_point="HTTP/HTTPS",
                    normalized_answer="C",
                    is_correct=True,
                    score=100,
                    mastery_score=100,
                    mastery_level="mastered",
                    feedback="回答正确。",
                ),
            ),
            patch(
                "app.domains.practice.attempts._create_practice_attempt",
                return_value={"id": "legacy-attempt-1", "created_at": "2026-05-09T00:00:00Z"},
            ),
            patch("app.application.practice.graph_facts.build_graph_fact_repositories", return_value=FakeRepos()),
            patch("app.application.practice.graph_facts.build_mastery_graph_with_repositories", return_value=FakeGraph()) as graph_builder,
            patch(
                "app.domains.practice.attempts._get_user_memory",
                return_value={"weak_points": [], "error_count": {}, "recent_topics": []},
            ),
            patch(
                "app.domains.practice.attempts._save_user_memory",
                return_value={"weak_points": [], "error_count": {}, "recent_topics": ["HTTP/HTTPS"], "last_session": ""},
            ),
        ):
            record_practice_attempt_and_update_memory(
                user_id="u1",
                session_id="",
                subject_id="computer-network",
                quiz_item=PracticeRecommendation(
                    question_id="q-http",
                    question="HTTP 属于哪一层？",
                    options=[
                        {"key": "A", "text": "网络层"},
                        {"key": "B", "text": "数据链路层"},
                        {"key": "C", "text": "应用层"},
                        {"key": "D", "text": "物理层"},
                    ],
                    correct_option="C",
                    explanation="HTTP 属于应用层协议。",
                    option_rationales={"C": "正确"},
                    knowledge_point="HTTP/HTTPS",
                    concept_id="computer-network.application.http-https",
                    concept_name="HTTP/HTTPS",
                    source_type="ai_generated",
                ),
                selected_option="C",
                graph_mastery_update=update_graph_mastery_from_practice_attempt,
            )

        self.assertEqual(graph_attempt_payloads[0]["id"], "practice:legacy-attempt-1")
        self.assertEqual(graph_attempt_payloads[0]["concept_id"], "computer-network.application.http-https")
        self.assertEqual(graph_attempt_payloads[0]["score"], 1.0)
        self.assertEqual(graph_states[0]["attempt_payloads"][0]["attempt_id"], "practice:legacy-attempt-1")
        graph_builder.assert_called_once()


if __name__ == "__main__":
    unittest.main()
