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

from app.orchestration.graphs.orchestrator.child_invokers import (
    ChildGraphInvokerFactory,
    MasteryEvaluationGraphInvoker,
    QAGraphInvoker,
    QuestionGenerationGraphInvoker,
    _child_graph_update,
    _child_state,
    _child_trace_outputs,
)
from app.shared.schemas.agent_graphs import GraphType, SourcePolicy


class ChildGraphInvokerFactoryTest(unittest.TestCase):
    def test_factory_maps_child_graph_types(self) -> None:
        factory = ChildGraphInvokerFactory.from_state({"production_runtime": True})

        self.assertTrue(factory.production_runtime)
        self.assertIsInstance(factory.for_graph(GraphType.QA), QAGraphInvoker)
        self.assertIsInstance(factory.for_graph(GraphType.QUESTION_GENERATION), QuestionGenerationGraphInvoker)
        self.assertIsInstance(factory.for_graph(GraphType.MASTERY), MasteryEvaluationGraphInvoker)

    def test_factory_rejects_unsupported_graph_type(self) -> None:
        factory = ChildGraphInvokerFactory()

        with self.assertRaisesRegex(ValueError, "unsupported_child_graph_type:orchestrator"):
            factory.for_graph(GraphType.ORCHESTRATOR)

    def test_child_state_preserves_quiz_request_for_question_generation(self) -> None:
        quiz_request = {"action": "generate_practice_pack", "topic": "HTTP"}
        intent_decision = {"intent": "generate_question", "target_graph_type": "question_generation"}
        state = _child_state(
            {
                "run_id": "run-1",
                "user_id": "u1",
                "user_message": "帮我出题练习 HTTP",
                "source_policy": SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value,
                "quiz_request": quiz_request,
                "intent_decision": intent_decision,
                "production_runtime": True,
            },
            GraphType.QUESTION_GENERATION,
        )

        self.assertEqual(state["run_id"], "run-1:question_generation")
        self.assertEqual(state["graph_type"], GraphType.QUESTION_GENERATION.value)
        self.assertEqual(state["question"], "帮我出题练习 HTTP")
        self.assertEqual(state["source_policy"], SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value)
        self.assertEqual(state["quiz_request"], quiz_request)
        self.assertEqual(state["parent_intent_decision"], intent_decision)
        self.assertTrue(state["production_runtime"])

    def test_child_graph_update_wraps_payload_contract(self) -> None:
        update = _child_graph_update(GraphType.QA, {"final_response": {"answer": "ok"}})

        self.assertEqual(update["child_graph_result"]["task_type"], GraphType.QA.value)
        self.assertEqual(update["child_graph_result"]["status"], "succeeded")
        self.assertEqual(update["child_graph_result"]["content"]["final_response"]["answer"], "ok")
        self.assertIn("audit_event", update["child_graph_result"])
        self.assertEqual(update["child_graph_output"]["target_graph_type"], GraphType.QA.value)
        self.assertEqual(update["child_graph_output"]["payload"]["final_response"]["answer"], "ok")

    def test_child_trace_outputs_include_safe_qa_diagnostics(self) -> None:
        outputs = _child_trace_outputs(
            GraphType.QA,
            {
                "final_response": {
                    "answer": "HTTP 是应用层协议。",
                    "source_level": "notebook",
                    "ui_payload": {
                        "reasoning_summary": "安全推理摘要",
                        "selected_model_profile": {"model_id": "deepseek-v4-pro"},
                        "source_usage": "notebook",
                        "retrieval_report": {"diagnosis": "notebook_evidence_found"},
                    },
                },
                "runtime_summary": {
                    "retrieval_diagnosis": {"diagnosis": "notebook_evidence_found", "raw_count": 2},
                    "tool_calls_count": 1,
                    "tool_decision_rounds_count": 1,
                    "tool_decision_rounds": [
                        {
                            "round": 1,
                            "decision": "use_tool",
                            "tool": "notebook_retrieve",
                            "provider": "internal",
                        }
                    ],
                    "fallback_reason": "",
                },
                "tool_results": [
                    {
                        "capability": "notebook_retrieve",
                        "provider": "internal",
                        "status": "success",
                    }
                ],
                "learning_events": [{}],
                "errors": [],
            },
        )

        self.assertEqual(outputs["route"], "rag")
        self.assertEqual(outputs["model_name"], "deepseek-v4-pro")
        self.assertEqual(outputs["retrieval_diagnosis"]["diagnosis"], "notebook_evidence_found")
        self.assertEqual(outputs["tool_decision"]["tool_decision_rounds_count"], 1)
        self.assertEqual(outputs["tool_decision"]["capabilities"], ["notebook_retrieve"])
        self.assertEqual(outputs["tool_decision"]["sources"], ["notebook"])
        self.assertEqual(outputs["tool_decision"]["tool_decision_rounds"][0]["source"], "notebook")
        self.assertNotIn("provider", outputs["tool_decision"])
        self.assertNotIn("provider", outputs["tool_decision"]["tool_decision_rounds"][0])
        self.assertEqual(outputs["safe_reasoning_summary"], "安全推理摘要")

    def test_qa_invoker_fails_open_with_repair_event(self) -> None:
        invoker = QAGraphInvoker()

        with (
            patch.object(QAGraphInvoker, "_invoke_deterministic", side_effect=RuntimeError("boom")),
            patch(
                "app.orchestration.graphs.orchestrator.child_invokers._persist_fallback_learning_events_safely"
            ) as persist_events,
        ):
            update = invoker.invoke(
                {"run_id": "run-qa-fail", "user_id": "u1", "thread_id": "session-1", "user_message": "什么是 HTTP？"}
            )

        payload = update["child_graph_output"]["payload"]
        result = update["child_graph_result"]
        self.assertEqual(update["child_graph_output"]["target_graph_type"], GraphType.QA.value)
        self.assertEqual(result["task_type"], GraphType.QA.value)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["learning_events"][0]["event_type"], "answer_repaired")
        self.assertEqual(payload["adapter"], "qagraph")
        self.assertTrue(payload["final_response"]["answer"])
        self.assertEqual(payload["learning_events"][0]["event_type"], "answer_repaired")
        self.assertEqual(
            payload["learning_events"][0]["payload"]["source_object_id"],
            "qa_child_graph_failed:session-1:run-qa-fail",
        )
        self.assertEqual(payload["learning_events"][0]["payload"]["source_object_type"], "orchestrator_child_failure")
        self.assertIn(
            "answer_repaired:u1::orchestrator_child_failure:qa_child_graph_failed:session-1:run-qa-fail",
            payload["learning_events"][0]["payload"]["hash_key"],
        )
        self.assertEqual(payload["errors"][0]["code"], "qa_child_graph_failed")
        persist_events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
