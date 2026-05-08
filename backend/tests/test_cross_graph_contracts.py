from __future__ import annotations

import ast
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.orchestration.graphs.mastery.graph import build_graph as build_mastery_graph
from app.orchestration.graphs.orchestrator.graph import build_graph as build_orchestrator_graph
from app.orchestration.graphs.orchestrator.nodes import persist_audit_event, response_composer
from app.orchestration.graphs.qa.graph import build_graph as build_qa_graph
from app.orchestration.graphs.question_generation.graph import (
    build_graph as build_question_generation_graph,
)
from app.services.tooling.adapters.base import ToolAdapter
from app.services.tooling.executor import ToolExecutor
from app.services.tooling.policy import ToolPolicyResolver
from app.services.tooling.registry import ToolRegistry
from app.services.tooling.schemas import ToolExecutionRequest, ToolRegistration, ToolRiskLevel
from app.shared.schemas.agent_graphs import (
    FinalResponse,
    GraphType,
    LearningEvent,
    LearningEventType,
    MASTERY_CONSUMABLE_EVENT_TYPES,
    MASTERY_OUTPUT_EVENT_TYPES,
    QA_LEARNING_EVENT_TYPES,
    QUESTION_GENERATION_EVENT_TYPES,
    SourceLevel,
    SourcePolicy,
    ToolCapability,
    ToolResult,
    ToolStatus,
)


GRAPH_ROOT = REPO_ROOT / "backend" / "app" / "orchestration" / "graphs"

NON_MASTERY_EVENTS = set(QUESTION_GENERATION_EVENT_TYPES) | set(MASTERY_OUTPUT_EVENT_TYPES)


def _assert_json_serializable(testcase: unittest.TestCase, payload: Any) -> None:
    testcase.assertIsInstance(json.loads(json.dumps(payload, ensure_ascii=False, default=str)), (dict, list))


def _assert_no_runtime_objects(testcase: unittest.TestCase, payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            testcase.assertFalse(callable(value), f"State key {key!r} contains a callable runtime object")
            _assert_no_runtime_objects(testcase, value)
    elif isinstance(payload, list):
        for item in payload:
            testcase.assertFalse(callable(item), "State list contains a callable runtime object")
            _assert_no_runtime_objects(testcase, item)


def _py_files(*parts: str) -> list[Path]:
    root = GRAPH_ROOT.joinpath(*parts)
    return sorted(root.rglob("*.py"))


def _imported_names(path: Path) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            for alias in node.names:
                names.add(alias.name)
    return names


class CrossGraphContractsTest(unittest.TestCase):
    def test_graph_relationship_matrix_documents_required_boundaries(self) -> None:
        path = REPO_ROOT / "docs" / "agent-graphs" / "graph-relationship-matrix.md"
        content = path.read_text(encoding="utf-8")

        required_terms = {
            "QAGraph",
            "QuestionGenerationGraph",
            "MasteryEvaluationGraph",
            "LearningEvent",
            "ConceptRef",
            "EvidenceChunk",
            "ToolResult",
            "FinalResponse",
            "GraphError",
            "LearningEventRepository",
            "QuestionItemRepository",
            "MasterySnapshotRepository",
            "notebook_only",
            "web_search",
            "禁止业务 Graph 之间直接互相 import 或调用",
        }

        missing = {term for term in required_terms if term not in content}
        self.assertFalse(missing, f"graph relationship matrix missing required terms: {missing}")

    def test_old_learning_assistant_graph_runtime_is_removed_from_production_entrypoints(self) -> None:
        removed_paths = [
            REPO_ROOT / "backend" / "app" / "orchestration" / "graph",
            REPO_ROOT / "backend" / "app" / "orchestration" / "workflow",
            REPO_ROOT / "backend" / "app" / "application" / "chat" / "qagraph_shadow.py",
            REPO_ROOT / "backend" / "app" / "application" / "chat" / "graph_runtime.py",
            REPO_ROOT / "backend" / "app" / "application" / "chat" / "workflow_adapter.py",
        ]
        offenders = [str(path.relative_to(REPO_ROOT)) for path in removed_paths if path.exists()]
        self.assertEqual(offenders, [])

        service_content = (REPO_ROOT / "backend" / "app" / "application" / "chat" / "service.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "run_chat_workflow",
            "stream_chat_workflow",
            "schedule_qagraph_shadow",
            "GRAPH_RUNTIME_MODE",
            "GRAPH_CANARY_PERCENT",
        ):
            self.assertNotIn(forbidden, service_content)

    def test_business_graphs_do_not_import_each_other_directly(self) -> None:
        forbidden_by_graph = {
            "qa": (
                "app.orchestration.graphs.question_generation",
                "app.orchestration.graphs.mastery",
            ),
            "question_generation": (
                "app.orchestration.graphs.qa",
                "app.orchestration.graphs.mastery",
            ),
            "mastery": (
                "app.orchestration.graphs.qa",
                "app.orchestration.graphs.question_generation",
            ),
        }

        for graph_dir, forbidden_modules in forbidden_by_graph.items():
            for path in _py_files(graph_dir):
                imports = _imported_names(path)
                leaked = {
                    module
                    for module in imports
                    for forbidden in forbidden_modules
                    if module == forbidden or module.startswith(f"{forbidden}.")
                }
                self.assertFalse(
                    leaked,
                    f"{graph_dir} must not directly import sibling business graphs: {path} has {leaked}",
                )

    def test_business_graphs_do_not_import_provider_specific_tavily_modules(self) -> None:
        forbidden_modules = {
            "app.services.tooling.adapters.tavily",
            "app.services.tools.tavily_tool",
            "tavily",
        }
        forbidden_symbols = {"TavilyClient", "TavilyWebSearchAdapter"}

        for path in _py_files():
            imports = _imported_names(path)
            leaked_modules = {
                module
                for module in imports
                for forbidden in forbidden_modules
                if module == forbidden or module.startswith(f"{forbidden}.")
            }
            leaked_symbols = imports & forbidden_symbols
            self.assertFalse(
                leaked_modules or leaked_symbols,
                f"business graph must request capability, not Tavily provider directly: {path} has "
                f"{leaked_modules | leaked_symbols}",
            )

    def test_enterprise_graphs_compile_and_return_final_response_contract(self) -> None:
        cases = [
            (GraphType.QA, build_qa_graph, "什么是 HTTP？"),
            (GraphType.QUESTION_GENERATION, build_question_generation_graph, "帮我出题练习 HTTP"),
            (GraphType.MASTERY, build_mastery_graph, "评估我的掌握度"),
        ]

        for graph_type, builder, message in cases:
            with self.subTest(graph_type=graph_type.value):
                result = builder().compile().invoke(
                    {
                        "run_id": f"run-{graph_type.value}",
                        "user_id": "u1",
                        "user_message": message,
                        "graph_type": graph_type.value,
                        "source_policy": SourcePolicy.OPEN_TOOLS.value,
                    }
                )

                response = FinalResponse.model_validate(result["final_response"])
                self.assertTrue(response.answer)
                self.assertEqual(response.ui_payload["target_graph_type"], graph_type.value)
                _assert_json_serializable(self, result)
                _assert_no_runtime_objects(self, result)

    def test_orchestrator_intent_child_output_and_final_response_are_consistent(self) -> None:
        cases = [
            ("什么是 HTTP？", GraphType.QA.value),
            ("帮我出题练习 HTTP", GraphType.QUESTION_GENERATION.value),
            ("评估我的掌握度", GraphType.MASTERY.value),
            ("", GraphType.ORCHESTRATOR.value),
        ]

        compiled = build_orchestrator_graph().compile()
        for message, expected_graph_type in cases:
            with self.subTest(message=message or "<empty>"):
                result = compiled.invoke({"user_id": "u1", "thread_id": "t1", "user_message": message})
                response = FinalResponse.model_validate(result["final_response"])
                child = result["child_graph_output"]

                self.assertEqual(result["intent_decision"]["target_graph_type"], expected_graph_type)
                self.assertEqual(child["target_graph_type"], expected_graph_type)
                self.assertEqual(
                    response.ui_payload["child_graph_output"]["target_graph_type"],
                    expected_graph_type,
                )
                self.assertNotIn(
                    "orchestrator_routed",
                    {event.get("event_type") for event in result.get("learning_events", [])},
                )
                _assert_json_serializable(self, result)

    def test_orchestrator_response_composer_preserves_child_final_response_fields(self) -> None:
        child_response = FinalResponse(
            answer="子图回答",
            source_level=SourceLevel.NOTEBOOK,
            evidence_refs=["e1"],
            coach_actions=["explain"],
            mastery_signals={"strength": "weak"},
            ui_payload={"target_graph_type": GraphType.QA.value},
        )

        result = response_composer(
            {
                "intent_decision": {"target_graph_type": GraphType.QA.value},
                "child_graph_output": {
                    "target_graph_type": GraphType.QA.value,
                    "payload": {"final_response": child_response.model_dump(mode="json")},
                },
            }
        )
        response = FinalResponse.model_validate(result["final_response"])

        self.assertEqual(response.source_level, SourceLevel.NOTEBOOK)
        self.assertEqual(response.evidence_refs, ["e1"])
        self.assertEqual(response.coach_actions, ["explain"])
        self.assertEqual(response.mastery_signals, {"strength": "weak"})
        self.assertEqual(response.ui_payload["target_graph_type"], GraphType.QA.value)
        self.assertEqual(response.ui_payload["child_graph_output"]["target_graph_type"], GraphType.QA.value)

    def test_orchestrator_audit_event_includes_graph_run_id_for_facts(self) -> None:
        captured: list[dict[str, Any]] = []

        class FakeAuditRepository:
            def record_audit_event(self, payload: dict[str, Any]) -> None:
                captured.append(payload)

        result = persist_audit_event(
            {"run_id": "run-1", "intent_decision": {"intent": "qa"}, "final_response": {"answer": "ok"}},
            audit_repository=FakeAuditRepository(),
        )

        self.assertEqual(captured[0]["graph_run_id"], "run-1")
        self.assertEqual(captured[0]["node_name"], "orchestrator.audit")
        self.assertEqual(result["audit_events"][0]["graph_run_id"], "run-1")

    def test_business_graph_modules_do_not_import_provider_specific_tavily(self) -> None:
        forbidden_imports = {
            "app.services.tools.tavily_tool",
            "TavilyClient",
            "tavily_web_search",
            "TavilyWebSearchAdapter",
        }

        for path in _py_files():
            with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                imports = _imported_names(path)
                self.assertFalse(
                    imports & forbidden_imports,
                    f"{path} imports provider-specific Tavily symbols: {imports & forbidden_imports}",
                )

    def test_qa_tool_loop_uses_capability_names_not_provider_specific_branches(self) -> None:
        path = REPO_ROOT / "backend" / "app" / "domains" / "qa" / "tool_loop.py"
        content = path.read_text(encoding="utf-8")
        forbidden_literals = {
            "search_notebook_context",
            "tavily_web_search",
            "mcp_web_search",
            "mcp_web_read",
            "Tavily",
        }
        leaked = {literal for literal in forbidden_literals if literal in content}
        self.assertFalse(leaked, f"QA runtime tool loop must branch by capability only: {leaked}")

    def test_repository_write_boundaries_do_not_cross_static_imports(self) -> None:
        mastery_write_symbols = {
            "MasterySnapshotRepository",
            "upsert_snapshot",
            "record_attempt",
            "record_exposure",
            "user_knowledge_stats",
        }
        orchestrator_forbidden_symbols = {
            "QuestionItemRepository",
            "AttemptRepository",
            "MasterySnapshotRepository",
            "upsert_snapshot",
            "create_question_item",
            "create_attempt",
        }

        for graph_dir in ("qa", "question_generation"):
            for path in _py_files(graph_dir):
                content = path.read_text(encoding="utf-8")
                leaked = {symbol for symbol in mastery_write_symbols if symbol in content}
                self.assertFalse(
                    leaked,
                    f"{graph_dir} must not write mastery or attempts directly: {path} has {leaked}",
                )

        for path in _py_files("orchestrator"):
            content = path.read_text(encoding="utf-8")
            leaked = {symbol for symbol in orchestrator_forbidden_symbols if symbol in content}
            self.assertFalse(
                leaked,
                f"Orchestrator must not write domain fact repositories directly: {path} has {leaked}",
            )

    def test_notebook_only_blocks_web_search_capability(self) -> None:
        decision = ToolPolicyResolver().resolve(
            source_policy=SourcePolicy.NOTEBOOK_ONLY,
            capability=ToolCapability.WEB_SEARCH,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "source_policy_notebook_only")

    def test_tool_executor_uses_registration_risk_as_lower_bound(self) -> None:
        class FakeHighRiskWebSearchAdapter(ToolAdapter):
            registration = ToolRegistration(
                tool_id="fake_high_risk_web_search",
                provider="fake",
                capability=ToolCapability.WEB_SEARCH,
                risk_level=ToolRiskLevel.HIGH,
            )

            def __init__(self) -> None:
                self.calls = 0

            def invoke(self, request: ToolExecutionRequest) -> ToolResult:
                self.calls += 1
                return ToolResult(
                    tool_id=self.registration.tool_id,
                    provider=self.registration.provider,
                    capability=self.registration.capability,
                    status=ToolStatus.SUCCESS,
                    input_summary=request.input_summary,
                )

        adapter = FakeHighRiskWebSearchAdapter()
        registry = ToolRegistry()
        registry.register(adapter)
        result = ToolExecutor(registry=registry, policy_resolver=ToolPolicyResolver()).execute(
            ToolExecutionRequest(
                capability=ToolCapability.WEB_SEARCH,
                input_summary="HTTP/3",
                source_policy=SourcePolicy.OPEN_TOOLS.value,
                risk_level=ToolRiskLevel.LOW,
                test_mode=True,
            ),
            provider="fake",
        )

        self.assertEqual(result.status, ToolStatus.BLOCKED)
        self.assertEqual(result.error, "test_mode_blocks_high_risk_tool")
        self.assertEqual(adapter.calls, 0)

    def test_final_response_schema_accepts_cross_graph_payloads(self) -> None:
        response = FinalResponse(
            answer="ok",
            source_level=SourceLevel.MIXED,
            evidence_refs=["e1"],
            coach_actions=["explain_concept"],
            mastery_signals={"signal_strength": "weak"},
            ui_payload={"target_graph_type": GraphType.QA.value},
        )

        dumped = response.model_dump(mode="json")
        self.assertEqual(dumped["source_level"], SourceLevel.MIXED.value)
        _assert_json_serializable(self, dumped)

    def test_learning_event_types_are_mastery_consumable_or_explicitly_non_mastery(self) -> None:
        qa_event = LearningEvent(
            event_type=LearningEventType.QUESTION_ANSWERED.value,
            user_id="u1",
            graph_run_id="run-qa",
            payload={"source_level": SourceLevel.MODEL.value},
        )
        qgen_event = LearningEvent(
            event_type=LearningEventType.QUESTION_GENERATED.value,
            user_id="u1",
            graph_run_id="run-qgen",
            payload={"question_item_id": "q1"},
        )

        self.assertLessEqual(QA_LEARNING_EVENT_TYPES, MASTERY_CONSUMABLE_EVENT_TYPES)
        self.assertLessEqual(QUESTION_GENERATION_EVENT_TYPES, NON_MASTERY_EVENTS)
        self.assertIn(qa_event.event_type, MASTERY_CONSUMABLE_EVENT_TYPES)
        self.assertIn(qgen_event.event_type, NON_MASTERY_EVENTS)
        _assert_json_serializable(self, qa_event.model_dump(mode="json"))
        _assert_json_serializable(self, qgen_event.model_dump(mode="json"))

    def test_new_graph_outputs_only_allowed_learning_event_types(self) -> None:
        allowed = (
            set(QA_LEARNING_EVENT_TYPES)
            | set(QUESTION_GENERATION_EVENT_TYPES)
            | set(MASTERY_OUTPUT_EVENT_TYPES)
        )
        cases = [
            build_qa_graph().compile().invoke(
                {
                    "run_id": "run-qa-events",
                    "user_id": "u1",
                    "user_message": "什么是 HTTP？",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                }
            ),
            build_question_generation_graph().compile().invoke(
                {
                    "run_id": "run-qgen-events",
                    "user_id": "u1",
                    "user_message": "帮我出题练习 HTTP",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                }
            ),
            build_mastery_graph().compile().invoke(
                {
                    "run_id": "run-mastery-events",
                    "user_id": "u1",
                    "learning_events": [
                        LearningEvent(
                            event_type=LearningEventType.CONCEPT_EXPLAINED.value,
                            user_id="u1",
                            concept_id="HTTP",
                            graph_run_id="run-qa",
                            payload={"concept_id": "HTTP"},
                        ).model_dump(mode="json")
                    ],
                }
            ),
        ]

        for result in cases:
            for event in [
                *list(result.get("learning_events") or []),
                *list(result.get("output_learning_events") or []),
            ]:
                self.assertIn(event.get("event_type"), allowed)

    def test_mastery_output_events_do_not_reenter_consumable_event_set(self) -> None:
        self.assertFalse(set(MASTERY_OUTPUT_EVENT_TYPES) & set(MASTERY_CONSUMABLE_EVENT_TYPES))


if __name__ == "__main__":
    unittest.main()
