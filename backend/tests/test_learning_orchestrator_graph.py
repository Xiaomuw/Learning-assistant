from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.orchestration.graphs.orchestrator.graph import build_graph
from app.orchestration.graphs.orchestrator.schemas import OrchestratorIntent
from app.shared.schemas.agent_graphs import GraphType


class MockGraphRunRepository:
    def __init__(self) -> None:
        self.audit_events: list[dict] = []

    def record_audit_event(self, payload: dict) -> None:
        self.audit_events.append(payload)


class LearningOrchestratorGraphTest(unittest.TestCase):
    def test_graph_compiles(self) -> None:
        compiled = build_graph().compile()
        self.assertTrue(hasattr(compiled, "invoke"))

    def test_routes_default_learning_question_to_qa(self) -> None:
        result = build_graph().compile().invoke(
            {"user_id": "u1", "thread_id": "t1", "user_message": "什么是 HTTP？"}
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.QA.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QA.value)
        self.assertEqual(result["child_graph_output"]["target_graph_type"], GraphType.QA.value)
        self.assertEqual(result["final_response"]["ui_payload"]["target_graph_type"], GraphType.QA.value)

    def test_routes_question_generation_intent(self) -> None:
        result = build_graph().compile().invoke(
            {"user_id": "u1", "thread_id": "t1", "user_message": "帮我出题练习 HTTP"}
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.GENERATE_QUESTION.value)
        self.assertEqual(
            result["intent_decision"]["target_graph_type"],
            GraphType.QUESTION_GENERATION.value,
        )
        self.assertEqual(result["quiz_request"]["action"], "generate_practice_pack")
        self.assertEqual(result["quiz_request"]["topic"], "HTTP")
        self.assertEqual(result["child_graph_output"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)
        self.assertEqual(
            result["final_response"]["ui_payload"]["target_graph_type"],
            GraphType.QUESTION_GENERATION.value,
        )

    def test_routes_english_question_generation_intent(self) -> None:
        result = build_graph().compile().invoke(
            {"user_id": "u1", "thread_id": "t1", "user_message": "Generate two stack practice questions"}
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.GENERATE_QUESTION.value)
        self.assertEqual(result["quiz_request"]["action"], "generate_practice_pack")
        self.assertEqual(result["quiz_request"]["topic"], "stack")
        self.assertEqual(result["quiz_request"]["count"], 2)
        self.assertEqual(result["child_graph_output"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)

    def test_explicit_subject_quiz_request_overrides_session_topic(self) -> None:
        result = build_graph().compile().invoke(
            {
                "user_id": "u1",
                "thread_id": "t1",
                "notebook_id": "computer-network",
                "user_message": "帮我出一些有关数据与结构有关的题目",
                "chat_runtime_context": {
                    "session_memory": {"active_topic": "TCP"},
                    "memory": {"recent_topics": ["UDP"]},
                },
            }
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.GENERATE_QUESTION.value)
        self.assertEqual(result["quiz_request"]["topic"], "数据结构与算法")
        self.assertEqual(result["quiz_request"]["subject_id"], "data-structure")
        self.assertEqual(result["quiz_request"]["requested_topic"], "数据结构与算法")
        self.assertEqual(result["quiz_request"]["previous_topic"], "TCP")
        self.assertEqual(result["quiz_request"]["active_topic"], "数据结构与算法")
        self.assertTrue(result["quiz_request"]["should_switch_topic"])
        self.assertTrue(result["child_graph_output"]["payload"]["question_items"])
        stems = "\n".join(str(item.get("stem") or "") for item in result["child_graph_output"]["payload"]["question_items"])
        self.assertIn("数组", stems)
        self.assertNotIn("TCP", stems)
        self.assertEqual(result["child_graph_output"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)
        self.assertEqual(result["notebook_id"], "computer-network")

    def test_explicit_http_quiz_request_overrides_session_dns_topic(self) -> None:
        result = build_graph().compile().invoke(
            {
                "user_id": "u1",
                "thread_id": "t1",
                "notebook_id": "computer-network",
                "user_message": "给我出两道 HTTP 单选题\n请只给题目和选项",
                "chat_runtime_context": {
                    "session_memory": {"active_topic": "DNS"},
                    "memory": {"recent_topics": ["DNS"]},
                },
            }
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.GENERATE_QUESTION.value)
        self.assertEqual(result["quiz_request"]["topic"], "HTTP")
        self.assertEqual(result["quiz_request"]["requested_topic"], "HTTP")
        self.assertEqual(result["quiz_request"]["active_topic"], "HTTP")
        self.assertTrue(result["quiz_request"]["should_switch_topic"])
        self.assertEqual(result["child_graph_output"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)

    def test_clarifies_quiz_request_without_topic_or_context(self) -> None:
        result = build_graph().compile().invoke(
            {"user_id": "u1", "thread_id": "t1", "user_message": "帮我出点题"}
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertEqual(result["quiz_request"]["action"], "clarify_quiz_request")
        self.assertTrue(result["quiz_request"]["need_clarification"])
        self.assertTrue(result["quiz_clarification"]["recommended_options"])
        self.assertEqual(result["child_graph_output"]["payload"]["quiz_request"]["action"], "clarify_quiz_request")

    def test_routes_mastery_evaluation_intent(self) -> None:
        result = build_graph().compile().invoke(
            {"user_id": "u1", "thread_id": "t1", "user_message": "评估我的掌握度"}
        )

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.EVALUATE_MASTERY.value)
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.MASTERY.value)
        self.assertEqual(result["child_graph_output"]["target_graph_type"], GraphType.MASTERY.value)
        self.assertEqual(result["final_response"]["ui_payload"]["target_graph_type"], GraphType.MASTERY.value)

    def test_empty_message_routes_to_safe_fallback(self) -> None:
        result = build_graph().compile().invoke({"user_id": "u1", "user_message": ""})

        self.assertEqual(result["intent_decision"]["intent"], OrchestratorIntent.FALLBACK.value)
        self.assertTrue(result["errors"])
        self.assertIn("更明确", result["final_response"]["answer"])

    def test_persist_audit_event_can_use_mock_repository(self) -> None:
        repository = MockGraphRunRepository()
        result = build_graph(audit_repository=repository).compile().invoke(
            {"user_id": "u1", "thread_id": "t1", "user_message": "什么是 HTTP？"}
        )

        self.assertEqual(len(repository.audit_events), 1)
        self.assertEqual(repository.audit_events[0]["run_id"], result["run_id"])
        self.assertTrue(result["audit_events"])

    def test_persist_audit_event_fails_open_when_repository_is_unavailable(self) -> None:
        class FailingAuditRepository:
            def record_audit_event(self, payload: dict) -> None:
                raise RuntimeError("db unavailable")

        result = build_graph(audit_repository=FailingAuditRepository()).compile().invoke(
            {"user_id": "u1", "thread_id": "t1", "user_message": "什么是 HTTP？"}
        )

        self.assertTrue(result["final_response"]["answer"])
        self.assertTrue(result["audit_events"])
        self.assertEqual(result["audit_events"][0]["status"], "degraded")
        self.assertTrue(
            any(error["code"] == "orchestrator_audit_persist_unavailable" for error in result["errors"])
        )


if __name__ == "__main__":
    unittest.main()
