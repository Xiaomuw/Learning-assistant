from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.infrastructure.llm.langsmith import trace_run
from app.orchestration.graphs.orchestrator.schemas import ChildGraphOutput
from app.orchestration.graphs.orchestrator.state import OrchestratorState
from app.orchestration.graphs.shared.schemas import GraphType, SourcePolicy
from app.shared.schemas.subject import DEFAULT_SUBJECTS, normalize_subject_id


class ChildGraphInvoker(Protocol):
    """Adapter boundary for invoking a child graph from the Orchestrator."""

    graph_type: GraphType

    def invoke(self, state: OrchestratorState) -> dict[str, Any]:
        """Invoke the child graph and return an Orchestrator state update."""


@dataclass(frozen=True)
class QAGraphInvoker:
    production_runtime: bool = False
    graph_type: GraphType = GraphType.QA

    def invoke(self, state: OrchestratorState) -> dict[str, Any]:
        with _child_trace(self.graph_type, state) as run:
            result = self._invoke_production(state) if self.production_runtime else self._invoke_deterministic(state)
            payload = {
                "final_response": result.get("final_response") or {},
                "evidence": list(result.get("evidence") or []),
                "tool_results": list(result.get("tool_results") or []),
                "learning_events": list(result.get("learning_events") or []),
                "errors": list(result.get("errors") or []),
                "learning_event_count": len(result.get("learning_events") or []),
                "adapter": "qagraph",
            }
            run.end(outputs=_child_trace_outputs(self.graph_type, payload))
            return _child_graph_update(self.graph_type, payload)

    def _invoke_deterministic(self, state: OrchestratorState) -> dict[str, Any]:
        from app.orchestration.graphs.qa.graph import build_graph as build_qa_graph

        return build_qa_graph().compile().invoke(_child_state(state, self.graph_type))

    def _invoke_production(self, state: OrchestratorState) -> dict[str, Any]:
        from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL
        from app.orchestration.graphs.qa.adapter import ProductionQARuntimeAdapter
        from app.orchestration.graphs.qa.graph import build_graph as build_qa_graph
        from app.persistence.repositories.graph_facts import build_graph_fact_repositories, is_graph_facts_enabled
        from app.services.tooling.executor import ToolExecutor
        from app.services.tooling.policy import ToolPolicyResolver
        from app.services.tooling.registry import build_default_tool_registry

        runtime_context = state.get("chat_runtime_context") if isinstance(state.get("chat_runtime_context"), dict) else {}
        qa_runtime_context = {
            "graph_run_id": f"{state.get('run_id', '')}:{self.graph_type.value}",
            "stream_answer_tokens": bool(runtime_context.get("stream_answer_tokens")),
            "thinking_mode": bool(runtime_context.get("thinking_mode", False)),
        }
        if qa_runtime_context["stream_answer_tokens"]:
            try:
                from langgraph.config import get_stream_writer

                qa_runtime_context["stream_writer"] = get_stream_writer()
            except Exception:
                pass
        adapter = ProductionQARuntimeAdapter(
            model_name=str(runtime_context.get("model_name") or DEFAULT_CHAT_MODEL),
            user_id=str(runtime_context.get("user_id") or state.get("user_id") or ""),
            session_id=str(runtime_context.get("session_id") or state.get("thread_id") or ""),
            subject_id=normalize_subject_id(runtime_context.get("subject_id") or state.get("notebook_id")),
            subject_name=str(runtime_context.get("subject_name") or DEFAULT_SUBJECTS[0]["name"]),
            subject_description=str(runtime_context.get("subject_description") or ""),
            memory=dict(runtime_context.get("memory") or {}),
            short_term_messages=list(runtime_context.get("short_term_messages") or state.get("messages") or []),
            short_term_context=str(runtime_context.get("short_term_context") or ""),
            session_memory=dict(runtime_context.get("session_memory") or {}),
            session_memory_context=str(runtime_context.get("session_memory_context") or ""),
            long_term_context=str(runtime_context.get("long_term_context") or ""),
            runtime_context=qa_runtime_context,
            allow_tools=bool(runtime_context.get("allow_tools", True)),
            allow_search=bool(runtime_context.get("allow_search", True)),
        )
        event_repo = build_graph_fact_repositories().learning_events if is_graph_facts_enabled() else None
        tool_executor = ToolExecutor(
            registry=build_default_tool_registry(),
            policy_resolver=ToolPolicyResolver(),
        )
        return build_qa_graph(
            adapter=adapter,
            learning_event_repository=event_repo,
            tool_executor=tool_executor,
        ).compile().invoke(_child_state(state, self.graph_type))


@dataclass(frozen=True)
class QuestionGenerationGraphInvoker:
    production_runtime: bool = False
    graph_type: GraphType = GraphType.QUESTION_GENERATION

    def invoke(self, state: OrchestratorState) -> dict[str, Any]:
        with _child_trace(self.graph_type, state) as run:
            if self.production_runtime:
                from app.orchestration.graphs.question_generation.graph import (
                    build_production_graph as build_question_generation_graph,
                )
            else:
                from app.orchestration.graphs.question_generation.graph import build_graph as build_question_generation_graph

            result = build_question_generation_graph().compile().invoke(_child_state(state, self.graph_type))
            payload = {
                "final_response": result.get("final_response") or {},
                "question_items": list(result.get("question_items") or []),
                "question_item_ids": list(result.get("question_item_ids") or []),
                "quality_report": result.get("quality_report") or {},
                "generation_status": result.get("generation_status") or {},
                "learning_events": list(result.get("learning_events") or []),
                "errors": list(result.get("errors") or []),
                "quiz_request": state.get("quiz_request") or {},
                "adapter": "question_generation_graph",
            }
            run.end(outputs=_child_trace_outputs(self.graph_type, payload))
            return _child_graph_update(self.graph_type, payload)


@dataclass(frozen=True)
class MasteryEvaluationGraphInvoker:
    production_runtime: bool = False
    graph_type: GraphType = GraphType.MASTERY

    def invoke(self, state: OrchestratorState) -> dict[str, Any]:
        with _child_trace(self.graph_type, state) as run:
            if self.production_runtime:
                from app.orchestration.graphs.mastery.graph import build_production_graph as build_mastery_graph

                graph = build_mastery_graph(subject_id=str(state.get("notebook_id") or state.get("course_id") or "") or None)
            else:
                from app.orchestration.graphs.mastery.graph import build_graph as build_mastery_graph

                graph = build_mastery_graph()
            result = graph.compile().invoke(_child_state(state, self.graph_type))
            payload = {
                "final_response": result.get("final_response") or {},
                "mastery_snapshots": list(result.get("mastery_snapshots") or []),
                "mastery_snapshot_ids": list(result.get("mastery_snapshot_ids") or []),
                "mastery_updates": list(result.get("mastery_updates") or []),
                "next_actions": list(result.get("next_actions") or []),
                "recommendations": list(result.get("recommendations") or []),
                "learning_events": list(result.get("learning_events") or []),
                "errors": list(result.get("errors") or []),
                "adapter": "mastery_evaluation_graph",
            }
            run.end(outputs=_child_trace_outputs(self.graph_type, payload))
            return _child_graph_update(self.graph_type, payload)


class ChildGraphInvokerFactory:
    def __init__(self, *, production_runtime: bool = False) -> None:
        self.production_runtime = production_runtime

    @classmethod
    def from_state(cls, state: OrchestratorState) -> ChildGraphInvokerFactory:
        return cls(production_runtime=bool(state.get("production_runtime")))

    def for_graph(self, graph_type: GraphType) -> ChildGraphInvoker:
        invokers: dict[GraphType, ChildGraphInvoker] = {
            GraphType.QA: QAGraphInvoker(production_runtime=self.production_runtime),
            GraphType.QUESTION_GENERATION: QuestionGenerationGraphInvoker(production_runtime=self.production_runtime),
            GraphType.MASTERY: MasteryEvaluationGraphInvoker(production_runtime=self.production_runtime),
        }
        if graph_type not in invokers:
            raise ValueError(f"unsupported_child_graph_type:{graph_type.value}")
        return invokers[graph_type]


def _child_graph_update(graph_type: GraphType, payload: dict[str, Any]) -> dict[str, Any]:
    output = ChildGraphOutput(target_graph_type=graph_type, payload=payload)
    return {"child_graph_output": output.model_dump(mode="json")}


def _child_trace(graph_type: GraphType, state: OrchestratorState):
    runtime_context = state.get("chat_runtime_context") if isinstance(state.get("chat_runtime_context"), dict) else {}
    return trace_run(
        name=f"orchestrator.child.{graph_type.value}",
        run_type="chain",
        inputs={
            "graph_type": graph_type.value,
            "user_message": state.get("user_message") or "",
            "quiz_request": state.get("quiz_request") or {},
            "thinking_mode": bool(runtime_context.get("thinking_mode", False)),
            "model_name": str(runtime_context.get("model_name") or ""),
            "source_policy": str(state.get("source_policy") or SourcePolicy.OPEN_TOOLS.value),
        },
        metadata={
            "component": "ChildGraphInvoker",
            "graph_type": graph_type.value,
            "parent_run_id": str(state.get("run_id") or ""),
            "user_id": str(state.get("user_id") or ""),
            "session_id": str(state.get("thread_id") or ""),
            "subject_id": normalize_subject_id(state.get("notebook_id") or state.get("course_id")),
            "production_runtime": bool(state.get("production_runtime")),
            "thinking_mode": bool(runtime_context.get("thinking_mode", False)),
            "model_name": str(runtime_context.get("model_name") or ""),
        },
        tags=["learning-assistant", "child-graph", f"graph:{graph_type.value}"],
    )


def _child_trace_outputs(graph_type: GraphType, payload: dict[str, Any]) -> dict[str, Any]:
    generation_status = payload.get("generation_status") if isinstance(payload.get("generation_status"), dict) else {}
    quality_report = payload.get("quality_report") if isinstance(payload.get("quality_report"), dict) else {}
    return {
        "graph_type": graph_type.value,
        "answer": (payload.get("final_response") or {}).get("answer") if isinstance(payload.get("final_response"), dict) else "",
        "safe_reasoning_summary": (
            ((payload.get("final_response") or {}).get("ui_payload") or {}).get("reasoning_summary")
            if isinstance(payload.get("final_response"), dict)
            and isinstance((payload.get("final_response") or {}).get("ui_payload"), dict)
            else ""
        ),
        "reasoning_visibility": "safe_summary_only",
        "learning_event_count": len(payload.get("learning_events") or []),
        "error_count": len(payload.get("errors") or []),
        "evidence_count": len(payload.get("evidence") or []),
        "tool_result_count": len(payload.get("tool_results") or []),
        "question_item_count": len(payload.get("question_items") or []),
        "mastery_update_count": len(payload.get("mastery_updates") or []),
        "quality_passed": quality_report.get("passed"),
        "repair_attempt_count": generation_status.get("repair_attempt_count"),
        "degraded": generation_status.get("repair_degraded") or generation_status.get("ai_generation_failed"),
    }


def _child_state(state: OrchestratorState, graph_type: GraphType) -> dict[str, Any]:
    message = str(state.get("user_message") or "").strip()
    return {
        "run_id": f"{state.get('run_id', '')}:{graph_type.value}",
        "tenant_id": state.get("tenant_id", ""),
        "user_id": state.get("user_id", ""),
        "notebook_id": state.get("notebook_id"),
        "course_id": state.get("course_id"),
        "thread_id": state.get("thread_id"),
        "graph_type": graph_type.value,
        "graph_version": state.get("graph_version") or "0.1.0",
        "source_policy": str(state.get("source_policy") or SourcePolicy.OPEN_TOOLS.value),
        "user_message": message,
        "question": message,
        "messages": list(state.get("messages") or []),
        "concepts": list(state.get("concepts") or []),
        "evidence": list(state.get("evidence") or []),
        "tool_results": list(state.get("tool_results") or []),
        "learning_events": list(state.get("learning_events") or []),
        "errors": list(state.get("errors") or []),
        "quiz_request": state.get("quiz_request") or {},
        "chat_runtime_context": state.get("chat_runtime_context") or {},
        "production_runtime": bool(state.get("production_runtime")),
    }
