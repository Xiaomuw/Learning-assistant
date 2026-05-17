from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.orchestration.graphs.qa.adapter import QARuntimeAdapter
from app.orchestration.graphs.qa.nodes import (
    clarify_node,
    direct_answer_node,
    finalize_node,
    generate_answer_or_question_node,
    goal_router_node,
    grade_context_node,
    hard_fallback_node,
    normalize_node,
    out_of_scope_node,
    quality_gate_node,
    rethink_and_revise_node,
    retrieve_augmented_node,
    retrieve_core_408_node,
    route_after_goal_router,
    route_after_grade_context,
    route_after_quality_gate,
    route_after_web_knowledge_grade,
    upsert_web_staging_node,
    web_extract_node,
    web_knowledge_grade_node,
    web_query_rewrite_node,
    web_search_node_408,
    web_source_filter_node,
    web_to_408_note_node,
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
    graph.add_node("normalize", lambda state: normalize_node(state, tool_executor=tool_executor))
    graph.add_node("goal_router", goal_router_node)
    graph.add_node("retrieve_core_408", lambda state: retrieve_core_408_node(state, tool_executor=tool_executor))
    graph.add_node("grade_context", grade_context_node)
    graph.add_node("web_query_rewrite", web_query_rewrite_node)
    graph.add_node("web_search", lambda state: web_search_node_408(state, tool_executor=tool_executor))
    graph.add_node("web_source_filter", web_source_filter_node)
    graph.add_node("web_extract", lambda state: web_extract_node(state, tool_executor=tool_executor))
    graph.add_node("web_knowledge_grade", web_knowledge_grade_node)
    graph.add_node("web_to_408_note", web_to_408_note_node)
    graph.add_node("upsert_web_staging", upsert_web_staging_node)
    graph.add_node("retrieve_augmented", retrieve_augmented_node)
    graph.add_node("generate_answer_or_question", lambda state: generate_answer_or_question_node(state, adapter=adapter))
    graph.add_node("quality_gate", quality_gate_node)
    graph.add_node("rethink_and_revise", rethink_and_revise_node)
    graph.add_node("hard_fallback", hard_fallback_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("out_of_scope", lambda state: out_of_scope_node(state, adapter=adapter))
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "goal_router")
    graph.add_conditional_edges(
        source="goal_router",
        path=route_after_goal_router,
        path_map={
            "direct_answer": "direct_answer",
            "retrieve_core_408": "retrieve_core_408",
            "clarify": "clarify",
            "out_of_scope": "out_of_scope",
        },
    )
    graph.add_edge("retrieve_core_408", "grade_context")
    graph.add_conditional_edges(
        source="grade_context",
        path=route_after_grade_context,
        path_map={
            "generate_answer_or_question": "generate_answer_or_question",
            "web_query_rewrite": "web_query_rewrite",
            "hard_fallback": "hard_fallback",
        },
    )
    graph.add_edge("web_query_rewrite", "web_search")
    graph.add_edge("web_search", "web_source_filter")
    graph.add_edge("web_source_filter", "web_extract")
    graph.add_edge("web_extract", "web_knowledge_grade")
    graph.add_conditional_edges(
        source="web_knowledge_grade",
        path=route_after_web_knowledge_grade,
        path_map={
            "web_to_408_note": "web_to_408_note",
            "web_query_rewrite": "web_query_rewrite",
            "generate_answer_or_question": "generate_answer_or_question",
            "hard_fallback": "hard_fallback",
        },
    )
    graph.add_edge("web_to_408_note", "upsert_web_staging")
    graph.add_edge("upsert_web_staging", "retrieve_augmented")
    graph.add_edge("retrieve_augmented", "grade_context")
    graph.add_edge("generate_answer_or_question", "quality_gate")
    graph.add_conditional_edges(
        source="quality_gate",
        path=route_after_quality_gate,
        path_map={
            "finalize": "finalize",
            "rethink_and_revise": "rethink_and_revise",
            "generate_answer_or_question": "generate_answer_or_question",
            "web_query_rewrite": "web_query_rewrite",
            "hard_fallback": "hard_fallback",
        },
    )
    graph.add_edge("rethink_and_revise", "quality_gate")
    graph.add_edge("direct_answer", "finalize")
    graph.add_edge("clarify", "finalize")
    graph.add_edge("out_of_scope", "finalize")
    graph.add_edge("hard_fallback", "finalize")
    graph.add_edge("finalize", END)
    return graph


def invoke_graph(input_state: dict[str, Any]) -> dict[str, Any]:
    return build_graph().compile().invoke(input_state)
