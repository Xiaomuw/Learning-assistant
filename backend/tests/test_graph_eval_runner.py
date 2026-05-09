from __future__ import annotations

import os
import sys
import unittest
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.orchestration.graphs import eval_runner
from app.orchestration.graphs import langsmith_eval


class GraphEvalRunnerTest(unittest.TestCase):
    def test_langsmith_eval_import_does_not_load_dotenv(self) -> None:
        with (
            patch.dict(os.environ, {"LANGSMITH_TRACING": "false"}, clear=False),
            patch("dotenv.load_dotenv") as load_dotenv,
        ):
            before = os.environ.get("LANGSMITH_TRACING")
            importlib.reload(langsmith_eval)
            after = os.environ.get("LANGSMITH_TRACING")

        load_dotenv.assert_not_called()
        self.assertEqual(after, before)

    def test_graph_eval_runner_passes_default_deterministic_cases(self) -> None:
        with patch.dict(os.environ, {"GRAPH_EVAL_LANGSMITH": "false"}, clear=False):
            summary = eval_runner.run_graph_evals()

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["failed"], 0)
        self.assertGreaterEqual(summary["total"], 6)

    def test_graph_eval_runner_can_trace_sanitized_case_summary(self) -> None:
        captured: list[dict] = []

        class FakeTrace:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def end(self, *args, **kwargs):
                captured.append({"args": args, "kwargs": kwargs})

        with (
            patch.dict(os.environ, {"GRAPH_EVAL_LANGSMITH": "true"}, clear=False),
            patch("app.orchestration.graphs.eval_runner.trace_run", return_value=FakeTrace()) as trace,
        ):
            summary = eval_runner.run_graph_evals()

        self.assertEqual(summary["status"], "passed")
        self.assertGreater(trace.call_count, 0)
        encoded = str(captured)
        for forbidden in ("什么是", "HTTP 是", "notebook_context", "tool_args", "raw_output", "document"):
            self.assertNotIn(forbidden, encoded)

    def test_langsmith_eval_dataset_sync_is_disabled_by_default_and_sanitized(self) -> None:
        with patch.dict(os.environ, {"GRAPH_EVAL_LANGSMITH": "false"}, clear=False):
            summary = langsmith_eval.sync_eval_dataset()

        self.assertFalse(summary["synced"])
        self.assertEqual(summary["reason"], "GRAPH_EVAL_LANGSMITH disabled")
        langsmith_eval.assert_no_sensitive_eval_payload(summary)

    def test_langsmith_eval_remote_run_disabled_does_not_sync_or_create_client(self) -> None:
        with (
            patch.dict(os.environ, {"GRAPH_EVAL_LANGSMITH": "false"}, clear=False),
            patch("app.orchestration.graphs.langsmith_eval.sync_eval_dataset") as sync_eval_dataset,
        ):
            summary = langsmith_eval.run_remote_eval()

        self.assertFalse(summary["ran"])
        self.assertEqual(summary["reason"], "GRAPH_EVAL_LANGSMITH disabled")
        sync_eval_dataset.assert_not_called()

    def test_langsmith_eval_sync_creates_sanitized_dataset_examples(self) -> None:
        fake_client = Mock()
        fake_client.read_dataset.side_effect = RuntimeError("missing")
        fake_client.create_dataset.return_value = SimpleNamespace(id="dataset-1")
        fake_client.list_examples.return_value = []

        with patch.dict(os.environ, {"GRAPH_EVAL_LANGSMITH": "true"}, clear=False):
            summary = langsmith_eval.sync_eval_dataset(client=fake_client)

        self.assertTrue(summary["synced"])
        self.assertGreaterEqual(fake_client.create_example.call_count, 1)
        for call in fake_client.create_example.call_args_list:
            kwargs = call.kwargs
            self.assertIn("case_name", kwargs["inputs"])
            self.assertIn("expected_metrics", kwargs["outputs"])
            langsmith_eval.assert_no_sensitive_eval_payload(
                {
                    "inputs": kwargs["inputs"],
                    "outputs": kwargs["outputs"],
                    "metadata": kwargs["metadata"],
                }
            )

    def test_langsmith_eval_run_invokes_target_and_evaluators(self) -> None:
        fake_client = Mock()
        fake_client.read_dataset.return_value = SimpleNamespace(id="dataset-1")
        fake_client.list_examples.return_value = []
        captured: dict[str, object] = {}

        def fake_evaluate(target, *, data, evaluators, client, **kwargs):
            captured["data"] = data
            captured["evaluator_count"] = len(evaluators)
            output = target({"case_name": "qa_concept_filtered_retrieval", "graph_type": "qa"})
            captured["output"] = output
            for evaluator in evaluators:
                score = evaluator(inputs={"case_name": "qa_concept_filtered_retrieval"}, outputs=output)
                self.assertIn("key", score)
            return {"ok": True}

        with patch.dict(os.environ, {"GRAPH_EVAL_LANGSMITH": "true"}, clear=False):
            summary = langsmith_eval.run_remote_eval(client=fake_client, evaluate_fn=fake_evaluate)

        self.assertTrue(summary["ran"])
        self.assertEqual(captured["data"], summary["dataset_name"])
        self.assertEqual(captured["evaluator_count"], 4)
        langsmith_eval.assert_no_sensitive_eval_payload(captured["output"])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
