from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://graph_eval:graph_eval@127.0.0.1:5432/__graph_eval_only__",
)

from app.infrastructure.llm.langsmith import trace_run
from app.orchestration.graphs.mastery.graph import build_graph as build_mastery_graph
from app.orchestration.graphs.orchestrator.route_decider import BoundaryRoute, decide_route
from app.orchestration.graphs.qa.graph import build_graph as build_qa_graph
from app.orchestration.graphs.question_generation.graph import build_graph as build_qgen_graph
from app.shared.schemas.agent_graphs import FinalResponse, GraphType, SourcePolicy, ToolCapability


_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class GraphEvalCase:
    name: str
    graph_type: GraphType
    runner: Callable[[], dict[str, Any]]
    assertions: list[Callable[[dict[str, Any]], str | None]]
    expected_metrics: dict[str, Any] | None = None


def is_graph_eval_langsmith_enabled() -> bool:
    return str(os.getenv("GRAPH_EVAL_LANGSMITH", "")).strip().lower() in _TRUE_VALUES


def get_graph_eval_cases() -> list[GraphEvalCase]:
    return list(_cases())


def get_graph_eval_case(case_name: str) -> GraphEvalCase:
    for case in get_graph_eval_cases():
        if case.name == case_name:
            return case
    raise KeyError(f"unknown graph eval case: {case_name}")


def build_eval_case_example(case: GraphEvalCase) -> dict[str, Any]:
    return {
        "inputs": {
            "case_name": case.name,
            "graph_type": case.graph_type.value,
        },
        "outputs": {
            "expected_status": "passed",
            "expected_metrics": dict(case.expected_metrics or {}),
        },
        "metadata": {
            "source": "graph_eval_smoke",
            "dataset_version": "2026-05-05",
            "contains_raw_user_text": False,
            "raw_response_included": False,
        },
    }


def run_graph_eval_case(case_name: str) -> dict[str, Any]:
    return _run_case(get_graph_eval_case(case_name))


def run_graph_evals(case_names: list[str] | None = None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    selected = get_graph_eval_cases()
    if case_names:
        wanted = set(case_names)
        selected = [case for case in selected if case.name in wanted]
    for case in selected:
        item = _run_case(case)
        results.append(item)
    failed = [item for item in results if item["status"] != "passed"]
    return {
        "status": "failed" if failed else "passed",
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }


def main() -> int:
    summary = run_graph_evals()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["status"] != "passed" else 0


def _cases() -> list[GraphEvalCase]:
    return [
        GraphEvalCase(
            name="route_simple_fact",
            graph_type=GraphType.ORCHESTRATOR,
            runner=lambda: _route_eval_output(
                {
                    "run_id": "eval-route-simple",
                    "user_id": "eval-user",
                    "user_message": "1+1等于几",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                    "runtime_context": {"available_capabilities": [ToolCapability.WEB_SEARCH.value]},
                }
            ),
            assertions=[_assert_route(BoundaryRoute.SIMPLE_FACT), _assert_no_tool_request],
            expected_metrics={"route": BoundaryRoute.SIMPLE_FACT.value, "rag_allowed": False, "web_allowed": False},
        ),
        GraphEvalCase(
            name="route_exercise_generation",
            graph_type=GraphType.ORCHESTRATOR,
            runner=lambda: _route_eval_output(
                {
                    "run_id": "eval-route-practice",
                    "user_id": "eval-user",
                    "user_message": "帮我出几道一百以内加减法题",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                }
            ),
            assertions=[_assert_route(BoundaryRoute.PRACTICE_GENERATION), _assert_no_tool_request],
            expected_metrics={"route": BoundaryRoute.PRACTICE_GENERATION.value},
        ),
        GraphEvalCase(
            name="route_meta_tool_usage",
            graph_type=GraphType.ORCHESTRATOR,
            runner=lambda: _route_eval_output(
                {
                    "run_id": "eval-route-meta",
                    "user_id": "eval-user",
                    "user_message": "刚刚有联网搜索吗",
                    "messages": [
                        {
                            "role": "assistant",
                            "toolInvocationTrace": {
                                "toolCallCount": 0,
                                "toolCalls": [],
                                "didUseWebSearch": False,
                                "didUseAnyTool": False,
                            },
                        }
                    ],
                }
            ),
            assertions=[_assert_route(BoundaryRoute.META_TOOL_USAGE), _assert_route_uses_trace],
            expected_metrics={"route": BoundaryRoute.META_TOOL_USAGE.value, "uses_trace": True},
        ),
        GraphEvalCase(
            name="route_latest_allow_web",
            graph_type=GraphType.ORCHESTRATOR,
            runner=lambda: _route_eval_output(
                {
                    "run_id": "eval-route-fresh-web",
                    "user_id": "eval-user",
                    "user_message": "今年 GPT 发布到哪个版本了",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                    "runtime_context": {"available_capabilities": [ToolCapability.WEB_SEARCH.value]},
                }
            ),
            assertions=[_assert_route(BoundaryRoute.REALTIME_OR_FRESH), _assert_route_allow_web(True)],
            expected_metrics={"route": BoundaryRoute.REALTIME_OR_FRESH.value, "allow_web": True},
        ),
        GraphEvalCase(
            name="route_latest_without_web",
            graph_type=GraphType.ORCHESTRATOR,
            runner=lambda: _route_eval_output(
                {
                    "run_id": "eval-route-fresh-no-web",
                    "user_id": "eval-user",
                    "user_message": "今年 GPT 发布到哪个版本了",
                    "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                    "runtime_context": {"available_capabilities": [ToolCapability.WEB_SEARCH.value]},
                }
            ),
            assertions=[_assert_route(BoundaryRoute.REALTIME_OR_FRESH), _assert_route_allow_web(False)],
            expected_metrics={"route": BoundaryRoute.REALTIME_OR_FRESH.value, "allow_web": False},
        ),
        GraphEvalCase(
            name="qa_concept_filtered_retrieval",
            graph_type=GraphType.QA,
            runner=lambda: build_qa_graph().compile().invoke(
                {
                    "run_id": "eval-qa-model-only",
                    "user_id": "eval-user",
                    "user_message": "什么是 HTTP？",
                    "question_type": "concept",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                }
            ),
            assertions=[
                _assert_final_response,
                _assert_non_empty_answer,
                _assert_concept_filtered_tool_request,
                _assert_no_web_fallback_planned,
                _assert_has_learning_event("question_answered"),
            ],
            expected_metrics={
                "non_empty_response": True,
                "tool_requests": 1,
                "concept_filtered_retrieval": True,
                "empty_notebook_web_fallback": False,
            },
        ),
        GraphEvalCase(
            name="qa_explicit_web_fallback",
            graph_type=GraphType.QA,
            runner=lambda: build_qa_graph().compile().invoke(
                {
                    "run_id": "eval-qa-explicit-web",
                    "user_id": "eval-user",
                    "user_message": "HTTP/3 最新浏览器支持情况？",
                    "question_type": "concept",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                    "allow_web": True,
                }
            ),
            assertions=[
                _assert_final_response,
                _assert_non_empty_answer,
                _assert_web_fallback_planned_without_provider,
                _assert_has_learning_event("question_answered"),
            ],
            expected_metrics={"non_empty_response": True, "web_fallback_planned": True},
        ),
        GraphEvalCase(
            name="qa_tool_policy_stable_concept_no_tools",
            graph_type=GraphType.QA,
            runner=lambda: build_qa_graph().compile().invoke(
                {
                    "run_id": "eval-qa-tool-policy",
                    "user_id": "eval-user",
                    "user_message": "什么是数据库索引？",
                    "question_type": "concept",
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                }
            ),
            assertions=[_assert_final_response, _assert_non_empty_answer, _assert_no_tool_request],
            expected_metrics={"non_empty_response": True, "tool_requests": 0},
        ),
        GraphEvalCase(
            name="qa_notebook_only_insufficient",
            graph_type=GraphType.QA,
            runner=lambda: build_qa_graph().compile().invoke(
                {
                    "run_id": "eval-qa-notebook-only",
                    "user_id": "eval-user",
                    "user_message": "只根据我的 notebook 解释 HTTP",
                    "question_type": "concept",
                    "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                }
            ),
            assertions=[_assert_final_response, _assert_has_learning_event("insufficient_evidence")],
            expected_metrics={"notebook_only_no_fabrication": True},
        ),
        GraphEvalCase(
            name="qa_tutoring_sufficient_evidence",
            graph_type=GraphType.QA,
            runner=lambda: build_qa_graph().compile().invoke(
                {
                    "run_id": "eval-qa-tutoring-evidence",
                    "user_id": "eval-user",
                    "user_message": "请一步步解释 HTTP 请求响应模型",
                    "question_type": "concept",
                    "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                    "evidence": [
                        {
                            "id": "eval-evidence-http-model",
                            "source_type": "notebook",
                            "source_id": "chunk-http-model",
                            "text": "HTTP 使用请求-响应模型：客户端发送请求，服务器返回响应。",
                            "score": 0.92,
                        }
                    ],
                }
            ),
            assertions=[_assert_final_response, _assert_non_empty_answer, _assert_internal_evidence_sufficient],
            expected_metrics={"internal_evidence_sufficient": True, "non_empty_response": True},
        ),
        GraphEvalCase(
            name="qgen_evidence_grounded",
            graph_type=GraphType.QUESTION_GENERATION,
            runner=lambda: build_qgen_graph().compile().invoke(
                {
                    "run_id": "eval-qgen",
                    "user_id": "eval-user",
                    "graph_type": GraphType.QUESTION_GENERATION.value,
                    "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                    "user_message": "帮我出题练习 HTTP 默认端口",
                    "concepts": [{"concept_id": "http-port", "name": "HTTP 默认端口"}],
                    "evidence": [
                        {
                            "id": "eval-evidence-http-port",
                            "source_type": "notebook",
                            "source_id": "chunk-http-port",
                            "text": "HTTP 默认端口是 80，HTTPS 默认端口是 443。",
                            "score": 0.9,
                        }
                    ],
                }
            ),
            assertions=[
                _assert_final_response,
                _assert_non_empty_answer,
                _assert_qgen_quality_passed,
                _assert_has_learning_event("question_generated"),
            ],
            expected_metrics={"quality_passed": True, "source_refs_required": True},
        ),
        GraphEvalCase(
            name="mastery_attempt_bounded_update",
            graph_type=GraphType.MASTERY,
            runner=lambda: build_mastery_graph().compile().invoke(
                {
                    "run_id": "eval-mastery",
                    "user_id": "eval-user",
                    "graph_type": GraphType.MASTERY.value,
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                    "history_snapshots": [
                        {"user_id": "eval-user", "subject_id": "network", "concept_id": "HTTP", "p_mastery": 0.45}
                    ],
                    "attempt_payloads": [
                        {
                            "attempt_id": "eval-attempt-1",
                            "user_id": "eval-user",
                            "subject_id": "network",
                            "knowledge_point": "HTTP",
                            "is_correct": True,
                        }
                    ],
                }
            ),
            assertions=[
                _assert_final_response,
                _assert_has_output_learning_event("mastery_updated"),
                _assert_mastery_bounded,
            ],
            expected_metrics={"mastery_bounded": True},
        ),
        GraphEvalCase(
            name="mastery_weak_signal_small_delta",
            graph_type=GraphType.MASTERY,
            runner=lambda: build_mastery_graph().compile().invoke(
                {
                    "run_id": "eval-mastery-weak",
                    "user_id": "eval-user",
                    "graph_type": GraphType.MASTERY.value,
                    "source_policy": SourcePolicy.OPEN_TOOLS.value,
                    "history_snapshots": [
                        {"user_id": "eval-user", "subject_id": "network", "concept_id": "HTTP", "p_mastery": 0.8}
                    ],
                    "learning_events": [
                        {
                            "id": "eval-weak-event-1",
                            "event_type": "concept_explained",
                            "user_id": "eval-user",
                            "concept_id": "HTTP",
                            "graph_run_id": "eval-qa",
                            "payload": {"signal_strength": "weak"},
                        }
                    ],
                }
            ),
            assertions=[
                _assert_final_response,
                _assert_has_output_learning_event("mastery_updated"),
                _assert_mastery_bounded,
                _assert_weak_signal_small_delta,
            ],
            expected_metrics={"mastery_bounded": True, "weak_signal_small_delta": True},
        ),
    ]


def _route_eval_output(state: dict[str, Any]) -> dict[str, Any]:
    decision = decide_route(state)
    return {
        "route_decision": {
            "route": decision.route.value,
            "target_graph_type": decision.target_graph_type.value,
            "bypass_qagraph": decision.bypass_qagraph,
            "uses_trace": decision.uses_trace,
            "policy": decision.policy.model_dump(mode="json"),
        },
        "tool_requests": [],
        "tool_results": [],
        "trace_records": [
            {
                "stage": "route_decider",
                "route": decision.route.value,
                "allow_web": decision.policy.allow_web,
                "notebook_only": decision.policy.notebook_only,
                "uses_trace": decision.uses_trace,
            }
        ],
    }


def _run_case(case: GraphEvalCase) -> dict[str, Any]:
    t0 = time.perf_counter()
    status = "passed"
    failures: list[str] = []
    output: dict[str, Any] = {}
    try:
        output = case.runner()
        for assertion in case.assertions:
            failure = assertion(output)
            if failure:
                failures.append(failure)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        failures.append(f"{exc.__class__.__name__}: {exc}")
    if failures:
        status = "failed"
    latency_ms = int((time.perf_counter() - t0) * 1000)
    item = {
        "name": case.name,
        "case_name": case.name,
        "graph_type": case.graph_type.value,
        "status": status,
        "failures": failures,
        "latency_ms": latency_ms,
        "final_answer_empty": _final_answer_empty(output),
        "evidence_count": len(list(output.get("evidence") or [])),
        "tool_request_count": len(list(output.get("tool_requests") or [])),
        "tool_result_count": len(list(output.get("tool_results") or [])),
        "learning_event_count": len(list(output.get("learning_events") or output.get("output_learning_events") or [])),
        "error_count": len(list(output.get("errors") or [])),
    }
    _trace_eval_case(item)
    return item


def _trace_eval_case(item: dict[str, Any]) -> None:
    if not is_graph_eval_langsmith_enabled():
        return
    with trace_run(
        name=f"graph.eval.{item['name']}",
        run_type="chain",
        inputs={"case": item["name"], "graph_type": item["graph_type"]},
        metadata={"component": "graph_eval", "graph_type": item["graph_type"], "status": item["status"]},
        tags=["graph-eval", item["graph_type"]],
    ) as run:
        run.end(outputs={"result": item})


def _assert_final_response(output: dict[str, Any]) -> str | None:
    try:
        FinalResponse.model_validate(output.get("final_response") or {})
    except Exception as exc:
        return f"final_response_invalid:{exc.__class__.__name__}"
    return None


def _assert_non_empty_answer(output: dict[str, Any]) -> str | None:
    return "final_answer_empty" if _final_answer_empty(output) else None


def _assert_route(expected: BoundaryRoute) -> Callable[[dict[str, Any]], str | None]:
    def assertion(output: dict[str, Any]) -> str | None:
        decision = output.get("route_decision") or {}
        if not isinstance(decision, dict) or decision.get("route") != expected.value:
            return f"route_mismatch:{expected.value}"
        return None

    return assertion


def _assert_route_allow_web(expected: bool) -> Callable[[dict[str, Any]], str | None]:
    def assertion(output: dict[str, Any]) -> str | None:
        decision = output.get("route_decision") or {}
        policy = decision.get("policy") if isinstance(decision, dict) else {}
        if not isinstance(policy, dict) or bool(policy.get("allow_web")) is not expected:
            return f"route_allow_web_mismatch:{expected}"
        return None

    return assertion


def _assert_route_uses_trace(output: dict[str, Any]) -> str | None:
    decision = output.get("route_decision") or {}
    if not isinstance(decision, dict) or decision.get("uses_trace") is not True:
        return "route_trace_not_used"
    return None


def _assert_has_learning_event(event_type: str) -> Callable[[dict[str, Any]], str | None]:
    def assertion(output: dict[str, Any]) -> str | None:
        events = list(output.get("learning_events") or [])
        if event_type not in {str(item.get("event_type") or "") for item in events if isinstance(item, dict)}:
            return f"missing_learning_event:{event_type}"
        return None

    return assertion


def _assert_has_output_learning_event(event_type: str) -> Callable[[dict[str, Any]], str | None]:
    def assertion(output: dict[str, Any]) -> str | None:
        events = list(output.get("output_learning_events") or [])
        if event_type not in {str(item.get("event_type") or "") for item in events if isinstance(item, dict)}:
            return f"missing_output_learning_event:{event_type}"
        return None

    return assertion


def _assert_mastery_bounded(output: dict[str, Any]) -> str | None:
    for update in list(output.get("mastery_updates") or []):
        value = update.get("p_mastery")
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
            return "mastery_out_of_bounds"
    return None


def _assert_no_tool_requests(output: dict[str, Any]) -> str | None:
    if list(output.get("tool_requests") or []):
        return "unexpected_tool_requests"
    if list(output.get("tool_results") or []):
        return "unexpected_tool_results"
    return None


def _assert_concept_filtered_tool_request(output: dict[str, Any]) -> str | None:
    requests = list(output.get("tool_requests") or [])
    notebook_requests = [
        item for item in requests if isinstance(item, dict) and item.get("capability") == ToolCapability.NOTEBOOK_RETRIEVE.value
    ]
    if len(notebook_requests) != 1:
        return "concept_filtered_request_count_mismatch"
    request = notebook_requests[0]
    if request.get("capability") != ToolCapability.NOTEBOOK_RETRIEVE.value:
        return "concept_filtered_request_wrong_capability"
    request_input = request.get("input") if isinstance(request, dict) else {}
    if not isinstance(request_input, dict) or not request_input.get("subject_id") or not request_input.get("concept_id"):
        return "concept_filtered_request_missing_filter"
    return None


def _assert_web_fallback_planned_without_provider(output: dict[str, Any]) -> str | None:
    requests = list(output.get("tool_requests") or [])
    capabilities = {str(item.get("capability") or "") for item in requests if isinstance(item, dict)}
    if ToolCapability.WEB_SEARCH.value not in capabilities:
        return "web_fallback_request_missing"
    encoded = json.dumps(requests, ensure_ascii=False).lower()
    if "tavily" in encoded:
        return "web_fallback_provider_leaked"
    return None


def _assert_no_web_fallback_planned(output: dict[str, Any]) -> str | None:
    requests = list(output.get("tool_requests") or [])
    capabilities = {str(item.get("capability") or "") for item in requests if isinstance(item, dict)}
    if ToolCapability.WEB_SEARCH.value in capabilities:
        return "unexpected_web_fallback_request"
    return None


def _assert_no_tool_request(output: dict[str, Any]) -> str | None:
    if list(output.get("tool_requests") or []):
        return "unexpected_tool_request"
    return None


def _assert_internal_evidence_sufficient(output: dict[str, Any]) -> str | None:
    confidence = output.get("evidence_confidence") or {}
    gate = output.get("evidence_gate") or {}
    if not isinstance(confidence, dict) or confidence.get("sufficient") is not True:
        return "internal_evidence_not_sufficient"
    if isinstance(gate, dict) and gate.get("sufficient") is not True:
        return "internal_evidence_gate_not_sufficient"
    return None


def _assert_planned_request_without_result(output: dict[str, Any]) -> str | None:
    if not list(output.get("tool_requests") or []):
        return "expected_planned_tool_request"
    if list(output.get("tool_results") or []):
        return "unexpected_tool_results"
    return None


def _assert_qgen_quality_passed(output: dict[str, Any]) -> str | None:
    report = output.get("quality_report") or {}
    if not isinstance(report, dict) or report.get("passed") is not True:
        return "qgen_quality_not_passed"
    response = output.get("final_response") or {}
    ui_payload = response.get("ui_payload") if isinstance(response, dict) else {}
    if not isinstance(ui_payload, dict) or ui_payload.get("quality_passed") is not True:
        return "qgen_final_response_quality_missing"
    for item in list(output.get("question_items") or []):
        if not item.get("source_refs"):
            return "qgen_missing_source_refs"
        if not item.get("answer_key"):
            return "qgen_missing_answer_key"
        if not item.get("rubric"):
            return "qgen_missing_rubric"
    return None


def _assert_weak_signal_small_delta(output: dict[str, Any]) -> str | None:
    for update in list(output.get("mastery_updates") or []):
        delta = abs(float(update.get("delta") or 0.0))
        if delta > 0.01:
            return "weak_signal_delta_too_large"
    return None


def _final_answer_empty(output: dict[str, Any]) -> bool:
    response = output.get("final_response") if isinstance(output, dict) else {}
    if not isinstance(response, dict):
        return True
    return not bool(str(response.get("answer") or "").strip())


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
