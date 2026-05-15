from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.domains.practice.quiz_request import build_quiz_clarification_panel, resolve_quiz_request
from app.orchestration.graphs.orchestrator.route_decider import BoundaryRoute, RouteDecision, decide_route
from app.orchestration.graphs.orchestrator.schemas import IntentDecision, OrchestratorIntent
from app.orchestration.graphs.orchestrator.state import OrchestratorState
from app.orchestration.graphs.shared.schemas import GraphType
from app.orchestration.graphs.shared.trace import build_trace_record
from app.shared.schemas.contracts import QuizRequestResolution


@dataclass(frozen=True)
class IntentRoutingContext:
    state: OrchestratorState
    message: str
    lowered_message: str
    quiz_resolution: QuizRequestResolution
    route_decision: RouteDecision


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
            route_decision=context.route_decision,
        )


class DecisionBoundaryDirectIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        route = context.route_decision.route
        if route in {BoundaryRoute.SIMPLE_FACT, BoundaryRoute.META_TOOL_USAGE}:
            return _decision_update(
                intent=OrchestratorIntent.DIRECT_RESPONSE,
                confidence=context.route_decision.confidence,
                reason=context.route_decision.reason,
                target_graph_type=GraphType.ORCHESTRATOR,
                route_decision=context.route_decision,
            )
        if route == BoundaryRoute.REALTIME_OR_FRESH and not context.route_decision.policy.allow_web:
            return _decision_update(
                intent=OrchestratorIntent.DIRECT_RESPONSE,
                confidence=context.route_decision.confidence,
                reason=context.route_decision.reason,
                target_graph_type=GraphType.ORCHESTRATOR,
                route_decision=context.route_decision,
            )
        return None


class QuizGenerateIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        resolution = context.quiz_resolution
        if resolution.action != "generate_practice_pack":
            return None
        if (
            context.route_decision.route == BoundaryRoute.PRACTICE_GENERATION
            and context.route_decision.target_graph_type == GraphType.ORCHESTRATOR
        ):
            panel = build_quiz_clarification_panel(resolution)
            return _decision_update(
                intent=OrchestratorIntent.FALLBACK,
                confidence=context.route_decision.confidence,
                reason=context.route_decision.reason,
                target_graph_type=GraphType.ORCHESTRATOR,
                quiz_request=resolution.model_dump(mode="json"),
                quiz_clarification=panel.model_dump(mode="json"),
                route_decision=context.route_decision,
            )
        return _decision_update(
            intent=OrchestratorIntent.GENERATE_QUESTION,
            confidence=0.9,
            reason=resolution.reason or "命中出题/练习意图。",
            target_graph_type=GraphType.QUESTION_GENERATION,
            quiz_request=resolution.model_dump(mode="json"),
            quiz_clarification={},
            route_decision=context.route_decision,
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
            route_decision=context.route_decision,
        )


class KeywordQuestionGenerationIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        if not any(token in context.message for token in ("出题", "练习题", "刷题", "生成题目", "来一组", "做一套", "小测一下")):
            return None
        return _decision_update(
            intent=OrchestratorIntent.GENERATE_QUESTION,
            confidence=0.82,
            reason="命中出题/练习意图。",
            target_graph_type=GraphType.QUESTION_GENERATION,
            route_decision=context.route_decision,
        )


class AnswerCheckIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        message = context.message
        if "答案" not in message and "批改" not in message and "哪里不对" not in message:
            return None
        if not any(token in message for token in ("对不对", "是否正确", "对吗", "错在哪", "哪里错", "哪里不对", "评估一下", "帮我批改", "批改一下")):
            return None
        return _decision_update(
            intent=OrchestratorIntent.QA,
            confidence=0.84,
            reason="命中答案讲解/判别意图，交给 QAGraph 解释。",
            target_graph_type=GraphType.QA,
            route_decision=context.route_decision,
        )


class MasteryIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        if not any(token in context.message for token in ("掌握度", "评估", "评分", "薄弱", "学习状态", "弱项", "短板")):
            return None
        return _decision_update(
            intent=OrchestratorIntent.EVALUATE_MASTERY,
            confidence=0.88,
            reason="命中掌握度评估意图。",
            target_graph_type=GraphType.MASTERY,
            route_decision=context.route_decision,
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
            route_decision=context.route_decision,
        )


class DefaultQAIntentRule:
    def decide(self, context: IntentRoutingContext) -> dict[str, Any] | None:
        return _decision_update(
            intent=OrchestratorIntent.QA,
            confidence=0.8,
            reason="默认学习问答意图。",
            target_graph_type=GraphType.QA,
            route_decision=context.route_decision,
        )


# Intent priority is part of the Orchestrator contract:
# request error > resolved quiz generation/clarification > keyword quiz fallback
# > mastery > help/status > default QA.
DEFAULT_INTENT_RULES: tuple[IntentRule, ...] = (
    RequestErrorIntentRule(),
    DecisionBoundaryDirectIntentRule(),
    QuizGenerateIntentRule(),
    QuizClarifyIntentRule(),
    KeywordQuestionGenerationIntentRule(),
    AnswerCheckIntentRule(),
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
    quiz_resolution = resolve_quiz_request(message, _quiz_context(state))
    context = IntentRoutingContext(
        state=state,
        message=message,
        lowered_message=message.lower(),
        quiz_resolution=quiz_resolution,
        route_decision=decide_route(state, quiz_resolution=quiz_resolution),
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
    route_decision: RouteDecision | None = None,
) -> dict[str, Any]:
    route = route_decision.route.value if route_decision is not None else ""
    route_policy = route_decision.policy.model_dump(mode="json") if route_decision is not None else {}
    decision = IntentDecision(
        intent=intent,
        confidence=confidence,
        reason=reason,
        target_graph_type=target_graph_type,
        route=route,
        route_policy=route_policy,
    )
    update: dict[str, Any] = {"intent_decision": decision.model_dump(mode="json")}
    if route_decision is not None:
        update["route_decision"] = route_decision.model_dump(mode="json")
        update["trace_records"] = [
            build_trace_record(
                "route_decider",
                route=route_decision.route.value,
                target_graph_type=route_decision.target_graph_type.value,
                bypass_qagraph=route_decision.bypass_qagraph,
                uses_trace=route_decision.uses_trace,
                confidence=route_decision.confidence,
                reason=route_decision.reason,
                allow_web=route_decision.policy.allow_web,
                notebook_only=route_decision.policy.notebook_only,
                has_web_search_tool=route_decision.policy.has_web_search_tool,
            )
        ]
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
