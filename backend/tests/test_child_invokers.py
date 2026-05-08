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

from app.orchestration.graphs.orchestrator.child_invokers import (
    ChildGraphInvokerFactory,
    MasteryEvaluationGraphInvoker,
    QAGraphInvoker,
    QuestionGenerationGraphInvoker,
    _child_graph_update,
    _child_state,
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
        state = _child_state(
            {
                "run_id": "run-1",
                "user_id": "u1",
                "user_message": "帮我出题练习 HTTP",
                "source_policy": SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value,
                "quiz_request": quiz_request,
                "production_runtime": True,
            },
            GraphType.QUESTION_GENERATION,
        )

        self.assertEqual(state["run_id"], "run-1:question_generation")
        self.assertEqual(state["graph_type"], GraphType.QUESTION_GENERATION.value)
        self.assertEqual(state["question"], "帮我出题练习 HTTP")
        self.assertEqual(state["source_policy"], SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value)
        self.assertEqual(state["quiz_request"], quiz_request)
        self.assertTrue(state["production_runtime"])

    def test_child_graph_update_wraps_payload_contract(self) -> None:
        update = _child_graph_update(GraphType.QA, {"final_response": {"answer": "ok"}})

        self.assertEqual(update["child_graph_output"]["target_graph_type"], GraphType.QA.value)
        self.assertEqual(update["child_graph_output"]["payload"]["final_response"]["answer"], "ok")


if __name__ == "__main__":
    unittest.main()
