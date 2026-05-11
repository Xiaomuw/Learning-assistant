from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.orchestration.graphs.orchestrator.nodes import (
    graph_router,
    invoke_qa_graph,
    load_learner_context,
    load_runtime_context,
    mastery_evaluation_graph_stub,
    persist_audit_event,
    persist_learning_events,
    question_generation_graph_stub,
    request_guard,
    response_composer,
    top_level_clarify_or_refuse,
)
from app.orchestration.graphs.orchestrator.router import (
    FALLBACK_NODE,
    MASTERY_EVALUATION_NODE,
    QA_NODE,
    QUESTION_GENERATION_NODE,
    route_after_intent,
)
from app.orchestration.graphs.orchestrator.state import OrchestratorState


REQUEST_GUARD_NODE = "request_guard"
LOAD_RUNTIME_CONTEXT_NODE = "load_runtime_context"
LOAD_LEARNER_CONTEXT_NODE = "load_learner_context"
GRAPH_ROUTER_NODE = "graph_router"
INTENT_ROUTER_NODE = GRAPH_ROUTER_NODE
PERSIST_LEARNING_EVENTS_NODE = "persist_learning_events"
RESPONSE_COMPOSER_NODE = "response_composer"
PERSIST_AUDIT_EVENT_NODE = "persist_audit_event"


def build_graph(
    *,
    audit_repository: Any | None = None,
    learning_event_repository: Any | None = None,
) -> StateGraph:
    graph = StateGraph(OrchestratorState)

    graph.add_node(REQUEST_GUARD_NODE, request_guard)
    graph.add_node(LOAD_RUNTIME_CONTEXT_NODE, load_runtime_context)
    graph.add_node(LOAD_LEARNER_CONTEXT_NODE, load_learner_context)
    graph.add_node(GRAPH_ROUTER_NODE, graph_router)
    graph.add_node(QA_NODE, invoke_qa_graph)
    graph.add_node(QUESTION_GENERATION_NODE, question_generation_graph_stub)
    graph.add_node(MASTERY_EVALUATION_NODE, mastery_evaluation_graph_stub)
    graph.add_node(FALLBACK_NODE, top_level_clarify_or_refuse)
    graph.add_node(
        PERSIST_LEARNING_EVENTS_NODE,
        lambda state: persist_learning_events(
            state,
            learning_event_repository=learning_event_repository,
        ),
    )
    graph.add_node(RESPONSE_COMPOSER_NODE, response_composer)

    def _persist(state: OrchestratorState) -> dict[str, Any]:
        return persist_audit_event(state, audit_repository=audit_repository)

    graph.add_node(PERSIST_AUDIT_EVENT_NODE, _persist)

    graph.set_entry_point(REQUEST_GUARD_NODE)
    graph.add_edge(REQUEST_GUARD_NODE, LOAD_RUNTIME_CONTEXT_NODE)
    graph.add_edge(LOAD_RUNTIME_CONTEXT_NODE, LOAD_LEARNER_CONTEXT_NODE)
    graph.add_edge(LOAD_LEARNER_CONTEXT_NODE, GRAPH_ROUTER_NODE)
    graph.add_conditional_edges(
        source=GRAPH_ROUTER_NODE,
        path=route_after_intent,
        path_map={
            QA_NODE: QA_NODE,
            QUESTION_GENERATION_NODE: QUESTION_GENERATION_NODE,
            MASTERY_EVALUATION_NODE: MASTERY_EVALUATION_NODE,
            FALLBACK_NODE: FALLBACK_NODE,
        },
    )
    for node in (QA_NODE, QUESTION_GENERATION_NODE, MASTERY_EVALUATION_NODE, FALLBACK_NODE):
        graph.add_edge(node, PERSIST_LEARNING_EVENTS_NODE)
    graph.add_edge(PERSIST_LEARNING_EVENTS_NODE, RESPONSE_COMPOSER_NODE)
    graph.add_edge(RESPONSE_COMPOSER_NODE, PERSIST_AUDIT_EVENT_NODE)
    graph.add_edge(PERSIST_AUDIT_EVENT_NODE, END)
    return graph
