from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domains.practice.quiz_request import build_quiz_clarification_panel, resolve_quiz_request
from app.orchestration.graphs.orchestrator.schemas import IntentDecision, OrchestratorIntent
from app.orchestration.graphs.orchestrator.state import OrchestratorState
from app.orchestration.graphs.shared.schemas import GraphType
from app.shared.schemas.contracts import QuizRequestResolution


@dataclass(frozen=True)
class IntentRoutingContext:
    state: OrchestratorState
    message: str
    lowered_message: str
    quiz_resolution: QuizRequestResolution


class IntentRule(Protocol):
    """Single responsibility routing rule for Orchestrator intent decisions."""

    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        """Return a state update when the rule matches, otherwise defer."""


class RequestErrorIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        if not context.state.get("errors"):
            return None
        return _decision_update(
            intent=OrchestratorIntent.FALLBACK,
            confidence=1.0,
            reason="request_guard 已记录错误，进入安全响应分支。",
            target_graph_type=GraphType.ORCHESTRATOR,
        )


class QuizGenerateIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        resolution = context.quiz_resolution
        if resolution.action != "generate_practice_pack":
            return None
        return _decision_update(
            intent=OrchestratorIntent.GENERATE_QUESTION,
            confidence=0.9,
            reason=resolution.reason or "命中出题/练习意图。",
            target_graph_type=GraphType.QUESTION_GENERATION,
            quiz_request=resolution.model_dump(mode="json"),
            quiz_clarification={},
        )


class QuizClarifyIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        resolution = context.quiz_resolution
        if resolution.action != "clarify_quiz_request":
            return None
        panel = build_quiz_clarification_panel(resolution)
        return _decision_update(
            intent=OrchestratorIntent.FALLBACK,
            confidence=0.92,
            reason=resolution.reason or "出题意图缺少练习主题，需要澄清。",
            target_graph_type=GraphType.ORCHESTRATOR,
            quiz_request=resolution.model_dump(mode="json"),
            quiz_clarification=panel.model_dump(mode="json"),
        )


class KeywordQuestionGenerationIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        if not any(token in context.message for token in ("出题", "练习题", "刷题", "生成题目")):
            return None
        return _decision_update(
            intent=OrchestratorIntent.GENERATE_QUESTION,
            confidence=0.82,
            reason="命中出题/练习意图。",
            target_graph_type=GraphType.QUESTION_GENERATION,
        )


class MasteryIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        if not any(token in context.message for token in ("掌握度", "评估", "评分", "薄弱", "学习状态")):
            return None
        return _decision_update(
            intent=OrchestratorIntent.EVALUATE_MASTERY,
            confidence=0.88,
            reason="命中掌握度评估意图。",
            target_graph_type=GraphType.MASTERY,
        )


class HelpStatusIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        if not (any(token in context.lowered_message for token in ("help", "status")) or context.message in {"?", "？"}):
            return None
        return _decision_update(
            intent=OrchestratorIntent.FALLBACK,
            confidence=0.75,
            reason="意图不完整，需要安全澄清。",
            target_graph_type=GraphType.ORCHESTRATOR,
        )


class DefaultQAIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        return _decision_update(
            intent=OrchestratorIntent.QA,
            confidence=0.8,
            reason="默认学习问答意图。",
            target_graph_type=GraphType.QA,
        )


# Intent priority is part of the Orchestrator contract:
# request error > resolved quiz generation/clarification > keyword quiz fallback
# > mastery > help/status > default QA.
DEFAULT_INTENT_RULES: tuple[IntentRule, ...] = (
    RequestErrorIntentRule(),
    QuizGenerateIntentRule(),
    QuizClarifyIntentRule(),
    KeywordQuestionGenerationIntentRule(),
    MasteryIntentRule(),
    HelpStatusIntentRule(),
    DefaultQAIntentRule(),
)


def resolve_intent_decision(
    state: OrchestratorState,
    *,
    rules: tuple[IntentRule, ...] = DEFAULT_INTENT_RULES,
) -> dict[str, Any]:
    message = str(state.get("user_message") or "").strip()
    context = IntentRoutingContext(
        state=state,
        message=message,
        lowered_message=message.lower(),
        quiz_resolution=resolve_quiz_request(message, _quiz_context(state)),
    )
    for rule in rules:
        update = rule.decide(context)
        if update is not None:
            return update
    return DefaultQAIntentRule().decide(context) or {}


def _decision_update(
    *,
    intent: OrchestratorIntent,
    confidence: float,
    reason: str,
    target_graph_type: GraphType,
    quiz_request: dict[str, Any] | None = None,
    quiz_clarification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = IntentDecision(
        intent=intent,
        confidence=confidence,
        reason=reason,
        target_graph_type=target_graph_type,
    )
    update: dict[str, Any] = {"intent_decision": decision.model_dump(mode="json")}
    if quiz_request is not None:
        update["quiz_request"] = quiz_request
    if quiz_clarification is not None:
        update["quiz_clarification"] = quiz_clarification
    return update


def _quiz_context(state: OrchestratorState) -> dict[str, Any]:
    runtime_context = state.get("chat_runtime_context") if isinstance(state.get("chat_runtime_context"), dict) else {}
    memory = runtime_context.get("memory") if isinstance(runtime_context.get("memory"), dict) else {}
    session_memory = (
        runtime_context.get("session_memory")
        if isinstance(runtime_context.get("session_memory"), dict)
        else {}
    )
    context: dict[str, Any] = {
        "user_id": state.get("user_id", ""),
        "notebook_id": state.get("notebook_id"),
        "course_id": state.get("course_id"),
        "thread_id": state.get("thread_id"),
        "subject_id": runtime_context.get("subject_id") or state.get("notebook_id"),
        "subject_name": runtime_context.get("subject_name"),
        "current_question": runtime_context.get("current_question"),
        "current_practice_question": runtime_context.get("current_practice_question"),
        "last_practice_pack": runtime_context.get("last_practice_pack"),
        "current_question_topic": runtime_context.get("current_question_topic"),
        "topic": runtime_context.get("topic"),
        "active_topic": runtime_context.get("active_topic"),
        "last_topic": runtime_context.get("last_topic"),
        "weak_points": runtime_context.get("weak_points"),
        "recent_topics": runtime_context.get("recent_topics"),
        "learner_stage": runtime_context.get("learner_stage"),
        "training_mode": runtime_context.get("training_mode"),
    }
    if session_memory.get("active_topic"):
        context["last_topic"] = session_memory.get("active_topic")
        context["active_topic"] = session_memory.get("active_topic")
    if session_memory.get("current_question"):
        context["current_question"] = session_memory.get("current_question")
    if session_memory.get("current_question_topic"):
        context["current_question_topic"] = session_memory.get("current_question_topic")
    if memory.get("recent_topics"):
        context["recent_topics"] = memory.get("recent_topics")
    if memory.get("weak_points"):
        context["weak_points"] = memory.get("weak_points")
    return {key: value for key, value in context.items() if value not in (None, "", [], {})}
