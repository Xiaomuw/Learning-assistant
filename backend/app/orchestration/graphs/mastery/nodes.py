from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.orchestration.graphs.mastery.schemas import (
    MasteryEvidence,
    MasterySnapshot,
    MasteryStatus,
    MasteryUpdate,
    NextLearningAction,
    SignalStrength,
)
from app.orchestration.graphs.mastery.state import MasteryEvaluationState
from app.orchestration.graphs.shared.schemas import FinalResponse, GraphType, LearningEvent, LearningEventType, build_learning_event


STRONG_EVENT_TYPES = {
    LearningEventType.PRACTICE_ATTEMPT_SUBMITTED.value,
    LearningEventType.ATTEMPT_SCORED.value,
}
WEAK_EVENT_TYPES = {
    LearningEventType.CONCEPT_EXPLAINED.value,
    LearningEventType.EVIDENCE_USED.value,
    LearningEventType.TOOL_FALLBACK_USED.value,
    LearningEventType.INSUFFICIENT_EVIDENCE.value,
    LearningEventType.ANSWER_REPAIRED.value,
    LearningEventType.MISCONCEPTION_DETECTED.value,
    LearningEventType.HINT_REQUESTED.value,
    LearningEventType.STUCK_REPORTED.value,
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        candidate = value
    else:
        try:
            candidate = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc)


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_subject_id(value: Any) -> str:
    text = str(value or "general").strip()
    return text or "general"


def _concept_from_payload(payload: dict[str, Any], fallback: str | None = None) -> str:
    for key in ("concept_id", "knowledge_point", "concept", "name"):
        value = payload.get(key)
        if isinstance(value, dict):
            value = value.get("concept_id") or value.get("name")
        text = str(value or "").strip()
        if text:
            return text
    return str(fallback or "").strip()


def _signal_id(prefix: str, payload: dict[str, Any]) -> str:
    return str(payload.get("attempt_id") or payload.get("id") or f"{prefix}:{len(str(payload))}")


def _hint_count(payload: dict[str, Any]) -> int:
    if bool(payload.get("hint_used")):
        return max(1, int(_as_float(payload.get("hint_count"), 1)))
    return max(0, int(_as_float(payload.get("hint_count"), 0)))


def _attempt_score(payload: dict[str, Any]) -> float:
    if "score" in payload:
        score = _as_float(payload.get("score"), 0.0)
        return _bounded(score / 100 if score > 1 else score)
    if "is_correct" in payload:
        return 1.0 if bool(payload.get("is_correct")) else 0.0
    if "correct" in payload:
        return 1.0 if bool(payload.get("correct")) else 0.0
    return 0.5


def _event_score(event_type: str, payload: dict[str, Any]) -> float:
    if "score" in payload or "rubric_score" in payload:
        raw = payload.get("score", payload.get("rubric_score"))
        score = _as_float(raw, 0.5)
        return _bounded(score / 100 if score > 1 else score)
    if "is_correct" in payload:
        return 1.0 if bool(payload.get("is_correct")) else 0.0
    if event_type in {
        LearningEventType.INSUFFICIENT_EVIDENCE.value,
        LearningEventType.ANSWER_REPAIRED.value,
        LearningEventType.MISCONCEPTION_DETECTED.value,
        LearningEventType.STUCK_REPORTED.value,
    }:
        return 0.25
    if event_type in {LearningEventType.HINT_REQUESTED.value, LearningEventType.TOOL_FALLBACK_USED.value}:
        return 0.4
    return 0.58


def _event_strength(event_type: str, payload: dict[str, Any]) -> SignalStrength | None:
    if event_type in STRONG_EVENT_TYPES:
        return SignalStrength.STRONG
    if event_type == LearningEventType.QUESTION_ANSWERED.value:
        if bool(payload.get("solver_verified")) or "is_correct" in payload:
            return SignalStrength.STRONG
        if "rubric_score" in payload or "score" in payload:
            return SignalStrength.MEDIUM
        return None
    return None


def objective_grader_node(state: MasteryEvaluationState) -> dict[str, Any]:
    consumed = set(state.get("consumed_signal_ids") or state.get("consumed_event_ids") or [])
    seen = set(consumed)
    evidence: list[dict[str, Any]] = []

    for attempt in state.get("attempt_payloads", []) or []:
        signal_id = _signal_id("attempt", attempt)
        concept_id = _concept_from_payload(attempt)
        if signal_id in seen or not concept_id:
            continue
        item = MasteryEvidence(
            signal_id=signal_id,
            signal_source="attempt",
            user_id=str(attempt.get("user_id") or state.get("user_id") or ""),
            concept_id=concept_id,
            subject_id=_normalize_subject_id(attempt.get("subject_id") or state.get("notebook_id")),
            strength=SignalStrength.STRONG,
            observed_score=_attempt_score(attempt),
            confidence=_bounded(_as_float(attempt.get("confidence"), 1.0)),
            hint_used=bool(attempt.get("hint_used")),
            hint_count=_hint_count(attempt),
            payload=dict(attempt),
        )
        evidence.append(item.model_dump(mode="json"))
        seen.add(signal_id)

    for raw_event in state.get("learning_events", []) or []:
        event = LearningEvent.model_validate(raw_event)
        if event.id in seen:
            continue
        strength = _event_strength(event.event_type, event.payload)
        concept_id = _concept_from_payload(event.payload, event.concept_id)
        if strength is None or not concept_id:
            continue
        item = MasteryEvidence(
            signal_id=event.id,
            signal_source=f"event:{event.event_type}",
            user_id=event.user_id,
            concept_id=concept_id,
            subject_id=_normalize_subject_id(event.payload.get("subject_id") or state.get("notebook_id")),
            strength=strength,
            observed_score=_event_score(event.event_type, event.payload),
            confidence=_bounded(_as_float(event.payload.get("confidence"), 0.85)),
            hint_used=bool(event.payload.get("hint_used")),
            hint_count=_hint_count(event.payload),
            payload=dict(event.payload),
        )
        evidence.append(item.model_dump(mode="json"))
        seen.add(event.id)

    return {"mastery_evidence": [*(state.get("mastery_evidence") or []), *evidence]}


def weak_signal_extractor_node(state: MasteryEvaluationState) -> dict[str, Any]:
    consumed = set(state.get("consumed_signal_ids") or state.get("consumed_event_ids") or [])
    seen = {item.get("signal_id") for item in state.get("mastery_evidence", []) or []}
    seen.update(consumed)
    evidence: list[dict[str, Any]] = []

    for raw_event in state.get("learning_events", []) or []:
        event = LearningEvent.model_validate(raw_event)
        concept_id = _concept_from_payload(event.payload, event.concept_id)
        if event.id in seen or event.event_type not in WEAK_EVENT_TYPES or not concept_id:
            continue
        item = MasteryEvidence(
            signal_id=event.id,
            signal_source=f"event:{event.event_type}",
            user_id=event.user_id,
            concept_id=concept_id,
            subject_id=_normalize_subject_id(event.payload.get("subject_id") or state.get("notebook_id")),
            strength=SignalStrength.WEAK,
            observed_score=_event_score(event.event_type, event.payload),
            confidence=_bounded(_as_float(event.payload.get("confidence"), 0.55)),
            hint_used=event.event_type == "hint_requested" or bool(event.payload.get("hint_used")),
            hint_count=max(1, _hint_count(event.payload)) if event.event_type == "hint_requested" else _hint_count(event.payload),
            payload=dict(event.payload),
        )
        evidence.append(item.model_dump(mode="json"))
        seen.add(event.id)

    for raw_snapshot in state.get("history_snapshots", []) or []:
        snapshot = dict(raw_snapshot)
        concept_id = _concept_from_payload(snapshot)
        if not concept_id:
            continue
        signal_id = _stale_signal_id(snapshot, concept_id)
        if signal_id in seen:
            continue
        stale_days = _stale_days(snapshot)
        if stale_days < 30:
            continue
        item = MasteryEvidence(
            signal_id=signal_id,
            signal_source="history:stale_review",
            user_id=str(snapshot.get("user_id") or state.get("user_id") or ""),
            concept_id=concept_id,
            subject_id=_normalize_subject_id(snapshot.get("subject_id") or state.get("notebook_id")),
            strength=SignalStrength.WEAK,
            observed_score=max(0.2, 0.45 - min(stale_days, 180) / 900),
            confidence=0.45,
            payload={
                "stale_days": stale_days,
                "last_practiced_at": snapshot.get("last_practiced_at", ""),
                "last_seen_at": snapshot.get("last_seen_at", ""),
                "updated_at": snapshot.get("updated_at", ""),
            },
        )
        evidence.append(item.model_dump(mode="json"))
        seen.add(signal_id)

    return {"mastery_evidence": [*(state.get("mastery_evidence") or []), *evidence]}


def evidence_aggregator_node(state: MasteryEvaluationState) -> dict[str, Any]:
    grouped: dict[str, list[MasteryEvidence]] = defaultdict(list)
    for raw in state.get("mastery_evidence", []) or []:
        item = MasteryEvidence.model_validate(raw)
        grouped[item.concept_id].append(item)

    aggregated: list[dict[str, Any]] = []
    ignored_weak_signal_ids: list[str] = []
    for concept_id, items in grouped.items():
        has_stronger = any(item.strength in {SignalStrength.STRONG, SignalStrength.MEDIUM} for item in items)
        for item in items:
            if has_stronger and item.strength == SignalStrength.WEAK:
                ignored_weak_signal_ids.append(item.signal_id)
                continue
            aggregated.append(item.model_dump(mode="json"))

    return {
        "aggregated_evidence": aggregated,
        "ignored_weak_signal_ids": ignored_weak_signal_ids,
    }


def _history_by_concept(state: MasteryEvaluationState) -> dict[str, float]:
    result: dict[str, float] = {}
    for raw in state.get("history_snapshots", []) or []:
        concept_id = _concept_from_payload(raw)
        if concept_id:
            score = raw.get("p_mastery", raw.get("mastery_score", 0.5))
            if _as_float(score, 0.5) > 1:
                score = _as_float(score, 50.0) / 100
            result[concept_id] = _bounded(_as_float(score, 0.5))
    return result


def _stale_days(snapshot: dict[str, Any]) -> int:
    latest = None
    for key in ("last_practiced_at", "last_seen_at", "updated_at"):
        candidate = _parse_datetime(snapshot.get(key))
        if candidate and (latest is None or candidate > latest):
            latest = candidate
    if latest is None:
        return 0
    return max(0, (datetime.now(timezone.utc) - latest).days)


def _stale_signal_id(snapshot: dict[str, Any], concept_id: str) -> str:
    marker = snapshot.get("last_practiced_at") or snapshot.get("last_seen_at") or snapshot.get("updated_at") or ""
    user_id = str(snapshot.get("user_id") or "")
    subject_id = _normalize_subject_id(snapshot.get("subject_id"))
    return f"stale:{user_id}:{subject_id}:{concept_id}:{marker}"


def _evidence_delta(evidence: MasteryEvidence) -> float:
    cap = {
        SignalStrength.STRONG: 0.18,
        SignalStrength.MEDIUM: 0.10,
        SignalStrength.WEAK: 0.03,
    }[evidence.strength]
    delta = cap * evidence.confidence * ((evidence.observed_score - 0.5) * 2)
    if delta > 0 and (evidence.hint_used or evidence.hint_count > 0):
        delta *= max(0.25, 1.0 - 0.25 * max(1, evidence.hint_count))
    return delta


def mastery_updater_node(state: MasteryEvaluationState) -> dict[str, Any]:
    history = _history_by_concept(state)
    grouped: dict[tuple[str, str, str], list[MasteryEvidence]] = defaultdict(list)
    for raw in state.get("aggregated_evidence", []) or []:
        evidence = MasteryEvidence.model_validate(raw)
        grouped[(evidence.user_id, evidence.subject_id, evidence.concept_id)].append(evidence)

    updates: list[dict[str, Any]] = []
    for (user_id, subject_id, concept_id), items in grouped.items():
        previous = history.get(concept_id, 0.5)
        delta = sum(_evidence_delta(item) for item in items)
        p_mastery = _bounded(previous + delta)
        update = MasteryUpdate(
            user_id=user_id,
            subject_id=subject_id,
            concept_id=concept_id,
            previous_p_mastery=previous,
            p_mastery=p_mastery,
            delta=round(p_mastery - previous, 6),
            evidence_ids=[item.id for item in items],
            consumed_signal_ids=[item.signal_id for item in items],
        )
        updates.append(update.model_dump(mode="json"))

    return {"mastery_updates": updates}


def status_classifier_node(state: MasteryEvaluationState) -> dict[str, Any]:
    updates: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    for raw in state.get("mastery_updates", []) or []:
        update = MasteryUpdate.model_validate(raw)
        if update.p_mastery >= 0.8:
            status = MasteryStatus.MASTERED
        elif update.p_mastery >= 0.5:
            status = MasteryStatus.LEARNING
        else:
            status = MasteryStatus.WEAK
        update.status = status
        updates.append(update.model_dump(mode="json"))
        snapshots.append(
            MasterySnapshot(
                user_id=update.user_id,
                subject_id=update.subject_id,
                concept_id=update.concept_id,
                p_mastery=update.p_mastery,
                status=status,
                evidence_ids=update.evidence_ids,
            ).model_dump(mode="json")
        )
    return {"mastery_updates": updates, "mastery_snapshots": snapshots}


def next_action_policy_node(state: MasteryEvaluationState) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for raw in state.get("mastery_updates", []) or []:
        update = MasteryUpdate.model_validate(raw)
        if update.status == MasteryStatus.MASTERED:
            action_type = "advance"
            priority = 3
            reason = "当前掌握度已达标，可以进入迁移题或下一概念。"
        elif update.status == MasteryStatus.LEARNING:
            action_type = "practice_variant"
            priority = 2
            reason = "当前处于学习中，建议用变式题巩固。"
        else:
            action_type = "review_prerequisite"
            priority = 1
            reason = "当前掌握度偏弱，建议先复盘概念和先修点。"
        actions.append(
            NextLearningAction(
                concept_id=update.concept_id,
                action_type=action_type,
                priority=priority,
                reason=reason,
            ).model_dump(mode="json")
        )
    return {"next_learning_actions": actions}


def response_composer_node(state: MasteryEvaluationState) -> dict[str, Any]:
    updates = state.get("mastery_updates") or []
    actions = state.get("next_learning_actions") or []
    output_events = []
    graph_run_id = str(state.get("run_id") or "")
    user_id = str(state.get("user_id") or "")
    for update in updates:
        output_events.append(
            build_learning_event(
                event_type=LearningEventType.MASTERY_UPDATED.value,
                user_id=str(update.get("user_id") or user_id),
                concept_id=str(update.get("concept_id") or ""),
                graph_run_id=graph_run_id,
                source_object_type="mastery_update",
                source_object_id="|".join(str(item) for item in update.get("consumed_signal_ids", []) or [])
                or f"{update.get('user_id') or user_id}:{update.get('subject_id') or 'general'}:{update.get('concept_id') or ''}",
                payload={
                    "subject_id": update.get("subject_id"),
                    "p_mastery": update.get("p_mastery"),
                    "status": update.get("status"),
                    "evidence_ids": update.get("evidence_ids", []),
                    "consumed_signal_ids": update.get("consumed_signal_ids", []),
                },
            ).model_dump(mode="json")
        )
    for action in actions:
        output_events.append(
            build_learning_event(
                event_type=LearningEventType.NEXT_STEP_RECOMMENDED.value,
                user_id=user_id,
                concept_id=str(action.get("concept_id") or ""),
                graph_run_id=graph_run_id,
                source_object_type="next_learning_action",
                source_object_id=f"{user_id}:{action.get('concept_id') or ''}:{action.get('action_type') or ''}",
                payload=dict(action),
            ).model_dump(mode="json")
        )
    if updates:
        answer = f"MasteryEvaluationGraph 已完成 {len(updates)} 个概念的掌握度更新。"
    else:
        answer = "MasteryEvaluationGraph 已编译；本次没有可消费的掌握度信号。"
    response = FinalResponse(
        answer=answer,
        coach_actions=[item["action_type"] for item in actions],
        mastery_signals={
            "updates": updates,
            "ignored_weak_signal_ids": state.get("ignored_weak_signal_ids", []),
        },
        ui_payload={
            "target_graph_type": GraphType.MASTERY.value,
            "adapter": "minimal",
            "snapshot_ids": state.get("mastery_snapshot_ids", []),
            "errors": list(state.get("errors") or []),
        },
    )
    return {
        "final_response": response.model_dump(mode="json"),
        "output_learning_events": output_events,
    }
