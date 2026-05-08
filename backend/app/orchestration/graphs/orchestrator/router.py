from __future__ import annotations

from app.orchestration.graphs.orchestrator.schemas import OrchestratorIntent
from app.orchestration.graphs.orchestrator.state import OrchestratorState


QA_NODE = "qa_graph"
QUESTION_GENERATION_NODE = "question_generation_graph"
MASTERY_EVALUATION_NODE = "mastery_evaluation_graph"
FALLBACK_NODE = "clarify_or_safe_response"

_INTENT_TO_NODE: dict[str, str] = {
    OrchestratorIntent.QA.value: QA_NODE,
    OrchestratorIntent.GENERATE_QUESTION.value: QUESTION_GENERATION_NODE,
    OrchestratorIntent.EVALUATE_MASTERY.value: MASTERY_EVALUATION_NODE,
    OrchestratorIntent.FALLBACK.value: FALLBACK_NODE,
}


def route_after_intent(state: OrchestratorState) -> str:
    decision = state.get("intent_decision") if isinstance(state.get("intent_decision"), dict) else {}
    intent = str(decision.get("intent") or OrchestratorIntent.FALLBACK.value)
    return _INTENT_TO_NODE.get(intent, FALLBACK_NODE)
