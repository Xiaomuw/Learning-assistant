from __future__ import annotations

import unittest


GRAPH_TEST_MODULES = (
    "backend.tests.test_agent_graph_contracts",
    "backend.tests.test_orchestrator_intent_rules",
    "backend.tests.test_child_invokers",
    "backend.tests.test_tooling_contracts",
    "backend.tests.test_learning_orchestrator_graph",
    "backend.tests.test_cross_graph_contracts",
    "backend.tests.test_graph_persistence_repositories",
    "backend.tests.test_graph_facts_backfill",
    "backend.tests.test_graph_migrations",
    "backend.tests.test_qa_graph_adapter",
    "backend.tests.test_qa_graph_runtime_adapter",
    "backend.tests.test_question_generation_graph_adapter",
    "backend.tests.test_mastery_graph_adapter",
    "backend.tests.test_graph_eval_runner",
    "backend.tests.test_practice_graph_facts",
)


def load_tests(
    loader: unittest.TestLoader,
    tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    _ = (tests, pattern)
    suite = unittest.TestSuite()
    for module_name in GRAPH_TEST_MODULES:
        suite.addTests(loader.loadTestsFromName(module_name))
    return suite
