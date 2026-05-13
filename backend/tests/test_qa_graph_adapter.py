from __future__ import annotations

import ast
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.domains.qa.schemas import AgentExecutionResult, AnswerSchema
from app.orchestration.graphs.qa.adapter import ProductionQARuntimeAdapter
from app.orchestration.graphs.qa.graph import build_graph
from app.shared.schemas.model_profile import ModelProfile
from app.shared.schemas.agent_graphs import (
    EvidenceChunk,
    FinalResponse,
    LearningEventType,
    SourceLevel,
    SourcePolicy,
    ToolCapability,
    ToolResult,
    ToolStatus,
)


QA_GRAPH_DIR = REPO_ROOT / "backend" / "app" / "orchestration" / "graphs" / "qa"


class InMemoryLearningEventRepository:
    def __init__(self) -> None:
        self.events = []

    def append(self, event):
        self.events.append(event)
        return event.id

    def list_for_user(self, *, user_id: str, limit: int = 100):
        return [item for item in self.events if item.user_id == user_id][:limit]


class QAGraphAdapterTest(unittest.TestCase):
    def test_qa_graph_node_boundary_uses_qa_scoped_nodes(self) -> None:
        self.assertEqual(
            set(build_graph().nodes),
            {
                "input_normalize",
                "qa_intent_classifier",
                "context_resolver",
                "concept_linker",
                "knowledge_router",
                "internal_retrieval",
                "evidence_judge",
                "web_search_if_needed",
                "evidence_merge",
                "answer_generate",
                "answer_quality_check",
                "answer_repair",
                "qa_clarification_response",
                "qa_result_compose",
                "compose_learning_events",
            },
        )

    def test_compile_and_return_grounded_final_response(self) -> None:
        evidence = EvidenceChunk(
            id="ev-http",
            source_type="notebook",
            source_id="chunk-1",
            text="HTTP 是浏览器和服务器之间交换请求与响应的应用层协议。",
            score=0.91,
        )

        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-1",
                "user_id": "u1",
                "thread_id": "t1",
                "notebook_id": "nb1",
                "user_message": "什么是 HTTP？",
                "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                "evidence": [evidence.model_dump(mode="json")],
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        event_types = {item["event_type"] for item in result["learning_events"]}

        self.assertIn("HTTP", response.answer)
        self.assertEqual(response.source_level, SourceLevel.NOTEBOOK)
        self.assertEqual(response.evidence_refs, ["ev-http"])
        self.assertIn("question_answered", event_types)
        self.assertIn("concept_explained", event_types)
        self.assertIn("evidence_used", event_types)
        self.assertEqual(result["tool_requests"], [])
        json.dumps(result, ensure_ascii=False)

    def test_notebook_only_insufficient_response_and_event(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-2",
                "user_id": "u1",
                "user_message": "什么是 HTTP？",
                "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                "evidence": [],
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        event_types = [item["event_type"] for item in result["learning_events"]]
        requested_capabilities = [item["capability"] for item in result["tool_requests"]]

        self.assertIn("资料不足", response.answer)
        self.assertEqual(response.source_level, SourceLevel.NONE)
        self.assertIn("question_answered", event_types)
        self.assertIn("insufficient_evidence", event_types)
        self.assertEqual(requested_capabilities, [ToolCapability.NOTEBOOK_RETRIEVE.value])
        self.assertNotIn(ToolCapability.WEB_SEARCH.value, requested_capabilities)

    def test_repeated_same_question_uses_message_id_for_learning_event_idempotency(self) -> None:
        base = {
            "user_id": "u1",
            "thread_id": "same-session",
            "user_message": "什么是 HTTP？",
            "source_policy": SourcePolicy.OPEN_TOOLS.value,
        }
        first = build_graph().compile().invoke({**base, "run_id": "run-1", "message_id": "msg-1"})
        second = build_graph().compile().invoke({**base, "run_id": "run-2", "message_id": "msg-2"})
        retry = build_graph().compile().invoke({**base, "run_id": "run-3", "message_id": "msg-1"})

        def question_answered_hash(result: dict) -> str:
            for event in result["learning_events"]:
                if event["event_type"] == LearningEventType.QUESTION_ANSWERED.value:
                    return str(event["payload"].get("hash_key") or "")
            return ""

        self.assertNotEqual(question_answered_hash(first), question_answered_hash(second))
        self.assertEqual(question_answered_hash(first), question_answered_hash(retry))

    def test_open_tools_plans_capability_request_without_provider_name(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-3",
                "user_id": "u1",
                "user_message": "HTTP/3 最新浏览器支持情况？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "evidence": [],
            }
        )

        requested_capabilities = [item["capability"] for item in result["tool_requests"]]
        encoded_requests = json.dumps(result["tool_requests"], ensure_ascii=False)

        self.assertIn(ToolCapability.WEB_SEARCH.value, requested_capabilities)
        self.assertNotIn("tavily", encoded_requests.lower())

    def test_open_tools_stable_concept_plans_filtered_retrieval(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-stable-concept",
                "user_id": "u1",
                "user_message": "什么是 HTTP？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "evidence": [],
            }
        )

        self.assertEqual(
            [item["capability"] for item in result["tool_requests"]],
            [ToolCapability.NOTEBOOK_RETRIEVE.value, ToolCapability.WEB_SEARCH.value],
        )
        request_input = result["tool_requests"][0]["input"]
        self.assertEqual(request_input["subject_id"], "computer-network")
        self.assertEqual(request_input["concept_id"], "computer-network.application.http-https")
        self.assertFalse(result["web_search_attempted"])
        self.assertEqual(result["web_search_reason"], "planned_without_executor")

    def test_notebook_signal_plans_internal_then_web_if_evidence_insufficient(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-notebook-signal",
                "user_id": "u1",
                "user_message": "根据我的 notebook 解释 HTTP",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "evidence": [],
            }
        )

        requested_capabilities = [item["capability"] for item in result["tool_requests"]]
        self.assertEqual(
            requested_capabilities,
            [ToolCapability.NOTEBOOK_RETRIEVE.value, ToolCapability.WEB_SEARCH.value],
        )
        self.assertEqual(result["source_policy"], SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value)
        self.assertFalse(result["web_search_attempted"])

    def test_injected_tool_executor_can_supply_evidence_without_provider_coupling(self) -> None:
        class FakeToolExecutor:
            def __init__(self) -> None:
                self.capabilities = []

            def execute(self, request):
                self.capabilities.append(request.capability)
                return ToolResult(
                    tool_id=f"fake:{request.capability.value}",
                    provider="fake",
                    capability=request.capability,
                    status=ToolStatus.SUCCESS,
                    input_summary=request.input_summary,
                    evidence=[
                        EvidenceChunk(
                            id=f"ev-{request.capability.value}",
                            source_type="notebook",
                            source_id="chunk-1",
                            text="HTTP 是请求-响应协议。",
                            score=0.9,
                        )
                    ],
                )

        executor = FakeToolExecutor()
        result = build_graph(tool_executor=executor).compile().invoke(
            {
                "run_id": "run-qa-tools",
                "user_id": "u1",
                "user_message": "什么是 HTTP？",
                "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                "evidence": [],
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        self.assertEqual(executor.capabilities, [ToolCapability.NOTEBOOK_RETRIEVE])
        self.assertFalse(result["evidence_gate"]["insufficient"])
        self.assertEqual(response.evidence_refs, ["ev-notebook_retrieve"])

    def test_chat_question_graph_records_internal_node_outputs(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-v2-fields",
                "user_id": "u1",
                "user_message": "什么是 HTTP？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        self.assertEqual(result["normalized_question"], "什么是 HTTP？")
        self.assertEqual(result["intent_result"]["intent"], "concept_explain")
        self.assertIn("knowledge_routes", result)
        self.assertIn(result["evidence_judgement"]["status"], {"strong", "partial", "insufficient"})
        self.assertEqual(result["answer_quality"]["status"], "pass")
        self.assertEqual(result["source_usage"], "model")

    def test_meta_question_is_classified_as_meta(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-meta-model",
                "user_id": "u1",
                "user_message": "你是什么模型？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        self.assertEqual(result["intent_result"]["intent"], "meta")
        self.assertEqual(result["question_type"], "meta")
        self.assertEqual(result["qa_request"]["question_type"], "meta")
        self.assertEqual(result["source_usage"], "model")

    def test_domain_model_question_is_not_classified_as_meta(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-domain-model",
                "user_id": "u1",
                "user_message": "BERT 是什么模型？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        self.assertNotEqual(result["intent_result"]["intent"], "meta")
        self.assertEqual(result["question_type"], "qa")

    def test_context_resolver_expands_followup_question(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-followup",
                "user_id": "u1",
                "user_message": "继续讲这个",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "session_memory": {"active_topic": "HTTP 缓存"},
            }
        )

        self.assertTrue(result["context_dependency"]["is_context_dependent"])
        self.assertIn("HTTP 缓存", result["resolved_question"])

    def test_knowledge_router_uses_explicit_named_knowledge_base_without_default_notebook(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-multi-kb",
                "user_id": "u1",
                "notebook_id": "current-notebook",
                "user_message": "根据 HTTP 协议资料解释 HTTP",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "available_knowledge_bases": [
                    {"id": "kb-http", "name": "HTTP 协议资料", "description": "Web 协议与请求响应"},
                    {"id": "kb-sql", "name": "数据库索引", "description": "SQL 查询优化"},
                ],
            }
        )

        route_ids = [item["knowledge_base_id"] for item in result["knowledge_routes"]]
        self.assertLessEqual(len(route_ids), 3)
        self.assertIn("kb-http", route_ids)
        self.assertNotIn("current-notebook", route_ids)

    def test_time_sensitive_question_runs_web_after_internal_evidence_judge_before_answer(self) -> None:
        class CapturingAdapter:
            def __init__(self) -> None:
                self.evidence_ids = []

            def answer(self, **kwargs):
                evidence = kwargs["evidence"]
                self.evidence_ids = [item.id for item in evidence]
                return FinalResponse(
                    answer="HTTP/3 支持情况需要参考当前外部来源。",
                    source_level=SourceLevel.WEB,
                    evidence_refs=self.evidence_ids,
                    ui_payload={"answer_mode": "captured"},
                )

        class FakeToolExecutor:
            def __init__(self) -> None:
                self.capabilities = []

            def execute(self, request):
                self.capabilities.append(request.capability)
                if request.capability == ToolCapability.WEB_SEARCH:
                    return ToolResult(
                        tool_id="fake:web_search",
                        provider="fake",
                        capability=request.capability,
                        status=ToolStatus.SUCCESS,
                        input_summary=request.input_summary,
                        evidence=[
                            EvidenceChunk(
                                id="web-http3",
                                source_type="web",
                                source_id="https://example.test/http3",
                                text="HTTP/3 的浏览器支持需要以当前兼容性资料为准。",
                                score=0.9,
                            )
                        ],
                    )
                return ToolResult(
                    tool_id="fake:notebook_retrieve",
                    provider="fake",
                    capability=request.capability,
                    status=ToolStatus.SUCCESS,
                    input_summary=request.input_summary,
                    evidence=[],
                )

        executor = FakeToolExecutor()
        adapter = CapturingAdapter()
        result = build_graph(adapter=adapter, tool_executor=executor).compile().invoke(
            {
                "run_id": "run-qa-web-fallback",
                "user_id": "u1",
                "user_message": "HTTP/3 现在浏览器支持怎么样？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        self.assertIn(ToolCapability.WEB_SEARCH, executor.capabilities)
        self.assertTrue(result["web_search_attempted"])
        self.assertEqual(result["evidence_judgement"]["web_count"], 0)
        self.assertEqual([item["id"] for item in result["web_evidence"]], ["web-http3"])
        self.assertEqual(adapter.evidence_ids, ["web-http3"])
        self.assertEqual(result["source_usage"], "web")
        self.assertEqual(response.source_level, SourceLevel.WEB)
        self.assertEqual(response.evidence_refs, ["web-http3"])

    def test_unjudged_or_low_score_web_evidence_does_not_enter_final_refs(self) -> None:
        class FakeToolExecutor:
            def execute(self, request):
                return ToolResult(
                    tool_id="fake:web_search",
                    provider="fake",
                    capability=request.capability,
                    status=ToolStatus.SUCCESS,
                    input_summary=request.input_summary,
                    evidence=[
                        EvidenceChunk(
                            id="web-low-score",
                            source_type="web",
                            source_id="https://example.test/weak",
                            text="低相关网页证据。",
                            score=0.2,
                        )
                    ]
                    if request.capability == ToolCapability.WEB_SEARCH
                    else [],
                )

        result = build_graph(tool_executor=FakeToolExecutor()).compile().invoke(
            {
                "run_id": "run-qa-web-low-score",
                "user_id": "u1",
                "user_message": "HTTP/3 现在浏览器支持怎么样？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        self.assertEqual(result["evidence_judgement"]["web_count"], 0)
        self.assertNotIn("web-low-score", response.evidence_refs)
        self.assertEqual(response.source_level, SourceLevel.MODEL)

    def test_retrieval_tool_exception_returns_error_result_and_learning_event(self) -> None:
        class FailingToolExecutor:
            def execute(self, request):
                raise RuntimeError("tool down")

        result = build_graph(tool_executor=FailingToolExecutor()).compile().invoke(
            {
                "run_id": "run-qa-tool-error",
                "user_id": "u1",
                "user_message": "HTTP/3 现在浏览器支持怎么样？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        event_types = {item["event_type"] for item in result["learning_events"]}
        self.assertTrue(result["final_response"]["answer"])
        self.assertTrue(any(error["code"] == "qa_retrieval_tool_failed" for error in result["errors"]))
        self.assertTrue(any(item["status"] == ToolStatus.ERROR.value for item in result["tool_results"]))
        self.assertIn("question_answered", event_types)

    def test_notebook_only_blocks_web_quality_fallback(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-no-web",
                "user_id": "u1",
                "user_message": "HTTP/3 现在浏览器支持怎么样？",
                "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
            }
        )

        requested_capabilities = [item["capability"] for item in result["tool_requests"]]
        self.assertIn(ToolCapability.NOTEBOOK_RETRIEVE.value, requested_capabilities)
        self.assertNotIn(ToolCapability.WEB_SEARCH.value, requested_capabilities)
        self.assertFalse(result.get("web_search_attempted", False))

    def test_quality_gate_no_longer_routes_web_search(self) -> None:
        from app.orchestration.graphs.qa.nodes import should_run_web_search

        state = {
            "answer_quality": {"needs_web_search": True},
            "source_policy": SourcePolicy.OPEN_TOOLS.value,
            "web_search_attempted": False,
            "web_search_iteration": 0,
        }

        self.assertEqual(should_run_web_search(state), "evidence_merge")

    def test_answer_quality_failure_repairable_rewrites_once_with_evidence(self) -> None:
        evidence = EvidenceChunk(
            id="ev-http",
            source_type="notebook",
            source_id="chunk-1",
            text="HTTP 是应用层协议，采用请求-响应模型。",
            score=0.9,
        )

        class BadRefAdapter:
            def answer(self, **_kwargs):
                return FinalResponse(
                    answer="HTTP 是协议。",
                    source_level=SourceLevel.NOTEBOOK,
                    evidence_refs=["missing-ref"],
                )

        result = build_graph(adapter=BadRefAdapter()).compile().invoke(
            {
                "run_id": "run-qa-repair",
                "user_id": "u1",
                "thread_id": "t1",
                "user_message": "什么是 HTTP？",
                "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                "evidence": [evidence.model_dump(mode="json")],
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        event_types = {item["event_type"] for item in result["learning_events"]}
        self.assertEqual(result["repair_count"], 1)
        self.assertEqual(result["max_repair_count"], 1)
        self.assertEqual(result["answer_repair_attempt_count"], 1)
        self.assertEqual(result["answer_quality"]["status"], "pass")
        self.assertEqual(response.evidence_refs, ["ev-http"])
        self.assertEqual(response.ui_payload["answer_mode"], "answer_repaired")
        self.assertIn("answer_repaired", event_types)

    def test_answer_quality_failure_not_repairable_returns_clarification(self) -> None:
        class EmptyAnswerAdapter:
            def answer(self, **_kwargs):
                return FinalResponse(answer="", source_level=SourceLevel.MODEL)

        result = build_graph(adapter=EmptyAnswerAdapter()).compile().invoke(
            {
                "run_id": "run-qa-clarify",
                "user_id": "u1",
                "thread_id": "t1",
                "user_message": "HTTP/3 现在浏览器支持怎么样？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        self.assertEqual(result["repair_count"], 1)
        self.assertEqual(result["max_repair_count"], 1)
        self.assertEqual(result["answer_repair_attempt_count"], 1)
        self.assertEqual(response.source_level, SourceLevel.NONE)
        self.assertEqual(response.ui_payload["answer_mode"], "clarification_required")
        self.assertIn("缺少足够可靠的证据", response.answer)

    def test_parent_intent_is_recorded_but_not_used_for_cross_graph_routing(self) -> None:
        result = build_graph().compile().invoke(
            {
                "run_id": "run-qa-parent-intent",
                "user_id": "u1",
                "user_message": "什么是 HTTP？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "parent_intent_decision": {"intent": "qa", "target_graph_type": "qa"},
            }
        )

        self.assertEqual(result["intent_result"]["intent"], "concept_explain")
        self.assertEqual(result["intent_result"]["parent_intent"], "qa")
        self.assertEqual(result["intent_alignment"]["status"], "aligned")

    def test_qa_graph_does_not_persist_learning_events_when_repository_is_supplied(self) -> None:
        repository = InMemoryLearningEventRepository()
        result = build_graph(learning_event_repository=repository).compile().invoke(
            {
                "run_id": "run-qa-4",
                "user_id": "u1",
                "user_message": "什么是 RAG？",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
            }
        )

        self.assertEqual(repository.events, [])
        self.assertTrue(result["learning_events"])
        self.assertNotIn("persisted_learning_event_ids", result)

    def test_qa_graph_static_boundaries_no_provider_or_mastery_write(self) -> None:
        forbidden_imports = {"TavilyClient", "tavily_web_search", "TavilyWebSearchAdapter"}
        forbidden_write_symbols = {
            "MasterySnapshotRepository",
            "upsert_snapshot",
            "record_attempt",
            "record_exposure",
            "user_knowledge_stats",
        }

        for path in sorted(QA_GRAPH_DIR.rglob("*.py")):
            with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                content = path.read_text(encoding="utf-8")
                tree = ast.parse(content)
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imported.add(node.module)
                        imported.update(alias.name for alias in node.names)

                self.assertFalse(imported & forbidden_imports)
                self.assertFalse({symbol for symbol in forbidden_write_symbols if symbol in content})
                self.assertNotIn(
                    "LearningEvent(",
                    content,
                    "QA graph business code must use build_learning_event() for stable idempotency fields.",
                )

    def test_production_runtime_adapter_maps_runtime_result_to_final_response(self) -> None:
        class FakeAgent:
            def run(self):
                return AgentExecutionResult(
                    execution_mode="structured_output",
                    answer=AnswerSchema(
                        topic="HTTP",
                        thinking="HTTP 是应用层协议。",
                        steps=["HTTP 使用请求-响应模型"],
                        similar=["HTTPS 是什么", "HTTP 缓存是什么"],
                        final_answer="HTTP 是浏览器和服务器之间交换请求与响应的应用层协议。",
                    ),
                    source_usage="model",
                    final_answer="HTTP 是浏览器和服务器之间交换请求与响应的应用层协议。",
                    selected_model_profile={"model_id": "test-model"},
                    primary_model_id="test-primary",
                    fallback_model_id="test-fallback",
                    fallback_used=True,
                    fallback_reason="unauthorized_model",
                )

        profile = ModelProfile(
            model_id="test-model",
            provider="test",
            family="TEST",
            supports_tool_calling=False,
            supports_structured_output=True,
            context_window=8000,
        )
        with (
            patch("app.orchestration.graphs.qa.adapter.get_model_profile", return_value=profile),
            patch("app.orchestration.graphs.qa.adapter.create_agent", return_value=FakeAgent()),
        ):
            response = ProductionQARuntimeAdapter(model_name="test-model").answer(
                question="什么是 HTTP？",
                question_type="concept",
                source_policy=SourcePolicy.OPEN_TOOLS.value,
                evidence=[],
                evidence_gate={"sufficient": False},
            )

        self.assertIn("HTTP", response.answer)
        self.assertEqual(response.ui_payload["answer_mode"], "production_qa_runtime")
        self.assertEqual(response.ui_payload["selected_model_profile"]["model_id"], "test-model")
        self.assertTrue(response.ui_payload["fallback_used"])
        self.assertEqual(response.ui_payload["primary_model_id"], "test-primary")
        self.assertEqual(response.ui_payload["fallback_model_id"], "test-fallback")

    def test_production_runtime_adapter_hides_provider_in_public_tool_results(self) -> None:
        class FakeAgent:
            def run(self):
                return AgentExecutionResult(
                    execution_mode="tool_calling",
                    answer=AnswerSchema(
                        topic="HTTP",
                        thinking="HTTP 是应用层协议。",
                        steps=["HTTP 使用请求响应模型"],
                        similar=["HTTPS 是什么", "HTTP 缓存是什么"],
                        final_answer="HTTP 是应用层协议。",
                    ),
                    source_usage="web",
                    final_answer="HTTP 是应用层协议。",
                    tool_calls=[
                        {
                            "name": "tavily_web_search",
                            "provider": "tavily",
                            "capability": "web_search",
                            "success": True,
                            "doc_count": 2,
                        }
                    ],
                )

        profile = ModelProfile(
            model_id="test-model",
            provider="test",
            family="TEST",
            supports_tool_calling=True,
            supports_structured_output=True,
            context_window=8000,
        )
        with (
            patch("app.orchestration.graphs.qa.adapter.get_model_profile", return_value=profile),
            patch("app.orchestration.graphs.qa.adapter.create_agent", return_value=FakeAgent()),
        ):
            result = ProductionQARuntimeAdapter(
                model_name="test-model",
                session_id="runtime-session",
                runtime_context={"message_id": "runtime-msg-1"},
            ).answer_with_contract(
                question="什么是 HTTP？",
                question_type="concept",
                source_policy=SourcePolicy.OPEN_TOOLS.value,
                evidence=[],
                evidence_gate={"sufficient": False},
            )

        encoded = json.dumps([item.model_dump(mode="json") for item in result.tool_results], ensure_ascii=False)
        self.assertIn('"source": "web"', encoded)
        self.assertNotIn("tavily", encoded.lower())
        self.assertTrue(
            any(
                str(event.payload.get("source_object_id") or "").startswith("qa_message:runtime-msg-1")
                for event in result.learning_events
            )
        )

    def test_production_runtime_adapter_forces_legacy_runtime_tools_off(self) -> None:
        captured: dict[str, object] = {}

        class FakeAgent:
            def run(self):
                return AgentExecutionResult(
                    execution_mode="structured_output",
                    answer=AnswerSchema(
                        topic="HTTP",
                        thinking="HTTP 是应用层协议。",
                        steps=["HTTP 使用请求-响应模型"],
                        similar=["HTTPS 是什么", "HTTP 缓存是什么"],
                        final_answer="HTTP 是应用层协议。",
                    ),
                    source_usage="notebook",
                    final_answer="HTTP 是应用层协议。",
                )

        def fake_create_agent(request, state, model_profile):
            captured["runtime_context"] = dict(request.runtime_context)
            captured["state"] = dict(state)
            captured["model_profile"] = model_profile
            return FakeAgent()

        profile = ModelProfile(
            model_id="test-model",
            provider="test",
            family="TEST",
            supports_tool_calling=True,
            supports_structured_output=True,
            context_window=8000,
        )
        evidence = [
            EvidenceChunk(
                id="ev-http",
                source_type="notebook",
                source_id="chunk-1",
                text="HTTP 是应用层协议。",
                score=0.9,
            )
        ]
        with (
            patch("app.orchestration.graphs.qa.adapter.get_model_profile", return_value=profile),
            patch("app.orchestration.graphs.qa.adapter.create_agent", side_effect=fake_create_agent),
        ):
            ProductionQARuntimeAdapter(
                model_name="test-model",
                allow_tools=True,
                allow_search=True,
                runtime_context={
                    "allow_tools": True,
                    "allow_search": True,
                    "guard": {"allow_tools": True, "allow_search": True, "reason": "caller_requested"},
                },
            ).answer(
                question="什么是 HTTP？",
                question_type="concept",
                source_policy=SourcePolicy.NOTEBOOK_ONLY.value,
                evidence=evidence,
                evidence_gate={"sufficient": True, "notebook_required": True},
            )

        runtime_context = captured["runtime_context"]
        self.assertEqual(runtime_context["allow_tools"], False)
        self.assertEqual(runtime_context["allow_search"], False)
        self.assertEqual(runtime_context["guard"]["allow_tools"], False)
        self.assertEqual(runtime_context["guard"]["allow_search"], False)
        self.assertEqual(
            runtime_context["guard"]["reason"],
            "qagraph_runtime_adapter_uses_precomputed_evidence_only",
        )
        self.assertEqual(runtime_context["qagraph_requested_allow_tools"], True)
        self.assertEqual(runtime_context["qagraph_requested_allow_search"], True)
        self.assertEqual(runtime_context["retrieved_docs"][0]["id"], "ev-http")


if __name__ == "__main__":
    unittest.main()
