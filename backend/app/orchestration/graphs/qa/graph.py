from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.orchestration.graphs.qa.adapter import QARuntimeAdapter
from app.orchestration.graphs.qa.nodes import (
    answer_generate_node,
    answer_quality_check_node,
    answer_repair_node,
    compose_learning_events,
    concept_linker_node,
    context_resolver_node,
    evidence_judge_node,
    evidence_merge_node,
    internal_retrieval_node,
    input_normalize_node,
    knowledge_router_node,
    qa_clarification_response_node,
    qa_intent_classifier_node,
    qa_result_compose_node,
    route_after_answer_quality,
    route_after_evidence_judge,
    web_search_if_needed_node,
)
from app.orchestration.graphs.qa.state import QAGraphState
from app.persistence.interfaces import LearningEventRepository
from app.services.tooling.executor import ToolExecutor


def build_graph(
    *,
    adapter: QARuntimeAdapter | None = None,
    learning_event_repository: LearningEventRepository | None = None,
    tool_executor: ToolExecutor | None = None,
) -> StateGraph:
    _ = learning_event_repository
    graph = StateGraph(QAGraphState)
    graph.add_node("input_normalize", lambda state: input_normalize_node(state, tool_executor=tool_executor))
    graph.add_node("qa_intent_classifier", qa_intent_classifier_node)
    graph.add_node("context_resolver", context_resolver_node)
    graph.add_node("concept_linker", concept_linker_node)
    graph.add_node("knowledge_router", knowledge_router_node)
    graph.add_node("internal_retrieval", lambda state: internal_retrieval_node(state, tool_executor=tool_executor))
    graph.add_node("evidence_judge", evidence_judge_node)
    graph.add_node("web_search_if_needed", lambda state: web_search_if_needed_node(state, tool_executor=tool_executor))
    graph.add_node("evidence_merge", evidence_merge_node)
    graph.add_node("answer_generate", lambda state: answer_generate_node(state, adapter=adapter))
    graph.add_node("answer_quality_check", answer_quality_check_node)
    graph.add_node("answer_repair", answer_repair_node)
    graph.add_node("qa_clarification_response", qa_clarification_response_node)
    graph.add_node("qa_result_compose", qa_result_compose_node)
    graph.add_node("compose_learning_events", compose_learning_events)

    graph.set_entry_point("input_normalize")
    graph.add_edge("input_normalize", "qa_intent_classifier")
    graph.add_edge("qa_intent_classifier", "context_resolver")
    graph.add_edge("context_resolver", "concept_linker")
    graph.add_edge("concept_linker", "knowledge_router")
    graph.add_edge("knowledge_router", "internal_retrieval")
    graph.add_edge("internal_retrieval", "evidence_judge")
    graph.add_conditional_edges(
        source="evidence_judge",
        path=route_after_evidence_judge,
        path_map={
            "web_search_if_needed": "web_search_if_needed",
            "evidence_merge": "evidence_merge",
        },
    )
    graph.add_edge("web_search_if_needed", "evidence_merge")
    graph.add_edge("evidence_merge", "answer_generate")
    graph.add_edge("answer_generate", "answer_quality_check")
    graph.add_conditional_edges(
        source="answer_quality_check",
        path=route_after_answer_quality,
        path_map={
            "qa_result_compose": "qa_result_compose",
            "answer_repair": "answer_repair",
            "qa_clarification_response": "qa_clarification_response",
        },
    )
    graph.add_edge("answer_repair", "answer_quality_check")
    graph.add_edge("qa_result_compose", "compose_learning_events")
    graph.add_edge("qa_clarification_response", "compose_learning_events")
    graph.add_edge("compose_learning_events", END)
    return graph


def invoke_graph(input_state: dict[str, Any]) -> dict[str, Any]:
    return build_graph().compile().invoke(input_state)
