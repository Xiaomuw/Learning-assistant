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

from app.application.chat.orchestrator_runtime import run_orchestrator_chat
from app.orchestration.graphs.orchestrator.graph import build_graph
from app.orchestration.graphs.orchestrator.router import (
    FALLBACK_NODE,
    MASTERY_EVALUATION_NODE,
    QA_NODE,
    QUESTION_GENERATION_NODE,
    route_after_intent,
)
from app.orchestration.graphs.shared.schemas import FinalResponse, GraphType, SourcePolicy


class OrchestratorWorkflowRoutesTest(unittest.TestCase):
    def test_route_after_intent_covers_current_graphs(self) -> None:
        self.assertEqual(route_after_intent({"intent_decision": {"intent": "qa"}}), QA_NODE)
        self.assertEqual(
            route_after_intent({"intent_decision": {"intent": "generate_question"}}),
            QUESTION_GENERATION_NODE,
        )
        self.assertEqual(
            route_after_intent({"intent_decision": {"intent": "evaluate_mastery"}}),
            MASTERY_EVALUATION_NODE,
        )
        self.assertEqual(route_after_intent({"intent_decision": {"intent": "fallback"}}), FALLBACK_NODE)
        self.assertEqual(route_after_intent({}), FALLBACK_NODE)

    def test_graph_topology_uses_enterprise_orchestrator_nodes(self) -> None:
        graph = build_graph()

        self.assertEqual(
            set(graph.nodes.keys()),
            {
                "request_guard",
                "load_runtime_context",
                "load_learner_context",
                "intent_router",
                QA_NODE,
                QUESTION_GENERATION_NODE,
                MASTERY_EVALUATION_NODE,
                FALLBACK_NODE,
                "response_composer",
                "persist_audit_event",
            },
        )
        self.assertNotIn("router", graph.nodes)
        self.assertNotIn("qa_agent_node", graph.nodes)
        self.assertNotIn("quiz_generate_node", graph.nodes)

    def test_orchestrator_routes_qa_question(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "orch-qa",
                "user_id": "u1",
                "thread_id": "t1",
                "user_message": "什么是 HTTP？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QA.value)
        self.assertEqual(result["child_graph_output"]["target_graph_type"], GraphType.QA.value)
        self.assertTrue(response.answer)

    def test_orchestrator_routes_question_generation(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "orch-qgen",
                "user_id": "u1",
                "thread_id": "t1",
                "user_message": "帮我出题练习 HTTP",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        self.assertEqual(result["intent_decision"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)
        self.assertEqual(result["child_graph_output"]["target_graph_type"], GraphType.QUESTION_GENERATION.value)
        self.assertIn("question_item_ids", result["child_graph_output"]["payload"])

    def test_orchestrator_runtime_maps_final_response_to_chat_state(self) -> None:
        final_response = FinalResponse(
            answer="HTTP 是应用层协议。",
            source_level="model",
            coach_actions=["explain_concept"],
            ui_payload={"target_graph_type": GraphType.QA.value},
        )
        graph_result = {
            "run_id": "orch-runtime",
            "intent_decision": {
                "intent": "qa",
                "target_graph_type": GraphType.QA.value,
                "confidence": 0.9,
            },
            "child_graph_output": {
                "target_graph_type": GraphType.QA.value,
                "payload": {"final_response": final_response.model_dump(mode="json")},
            },
            "final_response": final_response.model_dump(mode="json"),
            "errors": [],
        }
        with (
            patch("app.application.chat.orchestrator_runtime.is_graph_facts_enabled", return_value=False),
            patch("app.application.chat.orchestrator_runtime.build_orchestrator_graph") as builder,
            patch("app.application.chat.orchestrator_runtime.trace_run") as trace,
        ):
            trace.return_value.__enter__.return_value = trace.return_value
            trace.return_value.__exit__.return_value = None
            trace.return_value.end.return_value = None
            builder.return_value.compile.return_value.invoke.return_value = graph_result
            state = run_orchestrator_chat(
                {
                    "run_id": "orch-runtime",
                    "user_id": "u1",
                    "session_id": "s1",
                    "question": "什么是 HTTP？",
                    "subject_id": "general",
                },
                request_mode="sync",
            )

        self.assertEqual(state["question_type"], "concept")
        self.assertEqual(state["route"], "explain")
        self.assertEqual(state["final_answer"], "HTTP 是应用层协议。")
        self.assertEqual(state["graph_runtime"]["mode"], "orchestrator")


if __name__ == "__main__":
    unittest.main()
