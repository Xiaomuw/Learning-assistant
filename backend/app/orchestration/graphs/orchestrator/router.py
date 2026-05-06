from __future__ import annotations

from app.orchestration.graphs.orchestrator.schemas import OrchestratorIntent
from app.orchestration.graphs.orchestrator.state import OrchestratorState


QA_NODE = "qa_graph"
QUESTION_GENERATION_NODE = "question_generation_graph"
MASTERY_EVALUATION_NODE = "mastery_evaluation_graph"
FALLBACK_NODE = "clarify_or_safe_response"


def route_after_intent(state: OrchestratorState) -> str:
    decision = state.get("intent_decision") if isinstance(state.get("intent_decision"), dict) else {}
    intent = str(decision.get("intent") or OrchestratorIntent.FALLBACK.value)
    if intent == OrchestratorIntent.QA.value:
        return QA_NODE
    if intent == OrchestratorIntent.GENERATE_QUESTION.value:
        return QUESTION_GENERATION_NODE
    if intent == OrchestratorIntent.EVALUATE_MASTERY.value:
        return MASTERY_EVALUATION_NODE
    return FALLBACK_NODE

