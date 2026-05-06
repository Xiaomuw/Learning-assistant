from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.orchestration.graphs.qa.adapter import QARuntimeAdapter
from app.orchestration.graphs.qa.nodes import (
    answer_generate_node,
    answer_quality_check_node,
    compose_learning_events,
    context_resolver_node,
    evidence_judge_node,
    evidence_merge_node,
    final_response_node,
    input_normalize_node,
    intent_classifier_node,
    knowledge_router_node,
    persist_learning_events,
    retrieval_node,
    should_run_web_search,
    web_search_node,
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
    graph = StateGraph(QAGraphState)
    graph.add_node("input_normalize", input_normalize_node)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("context_resolver", context_resolver_node)
    graph.add_node("knowledge_router", knowledge_router_node)
    graph.add_node("retrieval", lambda state: retrieval_node(state, tool_executor=tool_executor))
    graph.add_node("evidence_judge", evidence_judge_node)
    graph.add_node("answer_generate", lambda state: answer_generate_node(state, adapter=adapter))
    graph.add_node("answer_quality_check", answer_quality_check_node)
    graph.add_node("web_search", lambda state: web_search_node(state, tool_executor=tool_executor))
    graph.add_node("evidence_merge", evidence_merge_node)
    graph.add_node("final_response_compose", final_response_node)
    graph.add_node("compose_learning_events", compose_learning_events)
    graph.add_node(
        "persist_learning_events",
        lambda state: persist_learning_events(
            state,
            learning_event_repository=learning_event_repository,
        ),
    )

    graph.set_entry_point("input_normalize")
    graph.add_edge("input_normalize", "intent_classifier")
    graph.add_edge("intent_classifier", "context_resolver")
    graph.add_edge("context_resolver", "knowledge_router")
    graph.add_edge("knowledge_router", "retrieval")
    graph.add_edge("retrieval", "evidence_judge")
    graph.add_edge("evidence_judge", "answer_generate")
    graph.add_edge("answer_generate", "answer_quality_check")
    graph.add_conditional_edges(
        "answer_quality_check",
        should_run_web_search,
        {
            "web_search": "web_search",
            "evidence_merge": "evidence_merge",
        },
    )
    graph.add_edge("web_search", "evidence_merge")
    graph.add_edge("evidence_merge", "final_response_compose")
    graph.add_edge("final_response_compose", "compose_learning_events")
    graph.add_edge("compose_learning_events", "persist_learning_events")
    graph.add_edge("persist_learning_events", END)
    return graph


def invoke_graph(input_state: dict[str, Any]) -> dict[str, Any]:
    return build_graph().compile().invoke(input_state)
