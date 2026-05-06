from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.orchestration.graphs.shared.schemas import GraphError, GraphErrorSeverity
from app.orchestration.graphs.mastery.nodes import (
    evidence_aggregator_node,
    mastery_updater_node,
    next_action_policy_node,
    objective_grader_node,
    response_composer_node,
    status_classifier_node,
    weak_signal_extractor_node,
)
from app.orchestration.graphs.mastery.state import MasteryEvaluationState
from app.persistence.interfaces import AttemptRepository, LearningEventRepository, MasterySnapshotRepository
from app.persistence.repositories.graph_facts import (
    CompositeAttemptRepository,
    CompositeMasterySnapshotRepository,
    build_graph_fact_repositories,
    is_graph_facts_enabled,
)
from app.persistence.repositories.mastery import (
    LegacyKnowledgeStatsMasteryRepository,
    LegacyPracticeAttemptRepository,
)


def _load_repository_inputs(
    *,
    learning_event_repository: LearningEventRepository | None,
    attempt_repository: AttemptRepository | None,
    mastery_repository: MasterySnapshotRepository | None,
):
    def load_repository_inputs_node(state: MasteryEvaluationState) -> dict[str, Any]:
        user_id = str(state.get("user_id") or "")
        result: dict[str, Any] = {}
        errors = list(state.get("errors") or [])
        if user_id and learning_event_repository is not None and not state.get("learning_events"):
            try:
                events = learning_event_repository.list_for_user(user_id=user_id, limit=100)
                result["learning_events"] = [event.model_dump(mode="json") for event in events]
            except Exception as exc:
                errors.append(
                    GraphError(
                        code="mastery_learning_event_repository_error",
                        message=exc.__class__.__name__,
                        node="load_repository_inputs",
                        severity=GraphErrorSeverity.WARNING,
                    ).model_dump(mode="json")
                )
        if user_id and attempt_repository is not None and not state.get("attempt_payloads"):
            try:
                result["attempt_payloads"] = attempt_repository.list_recent_attempts(user_id=user_id, limit=100)
            except Exception as exc:
                errors.append(
                    GraphError(
                        code="mastery_attempt_repository_error",
                        message=exc.__class__.__name__,
                        node="load_repository_inputs",
                        severity=GraphErrorSeverity.WARNING,
                    ).model_dump(mode="json")
                )
        if user_id and mastery_repository is not None and not state.get("history_snapshots"):
            try:
                result["history_snapshots"] = mastery_repository.list_snapshots(user_id=user_id, limit=100)
            except Exception as exc:
                errors.append(
                    GraphError(
                        code="mastery_snapshot_repository_error",
                        message=exc.__class__.__name__,
                        node="load_repository_inputs",
                        severity=GraphErrorSeverity.WARNING,
                    ).model_dump(mode="json")
                )
        if errors:
            result["errors"] = errors
        return result

    return load_repository_inputs_node


def _persist_snapshots(mastery_repository: MasterySnapshotRepository | None):
    def persist_snapshots_node(state: MasteryEvaluationState) -> dict[str, Any]:
        snapshot_ids: list[str] = []
        snapshots = state.get("mastery_snapshots", []) or []
        if mastery_repository is None:
            snapshot_ids = [str(item.get("id")) for item in snapshots if item.get("id")]
        else:
            for snapshot in snapshots:
                try:
                    snapshot_ids.append(mastery_repository.upsert_snapshot(dict(snapshot)))
                except Exception as exc:
                    existing_errors = list(state.get("errors") or [])
                    existing_errors.append(
                        GraphError(
                            code="mastery_snapshot_repository_write_error",
                            message=exc.__class__.__name__,
                            node="persist_snapshots",
                            severity=GraphErrorSeverity.WARNING,
                        ).model_dump(mode="json")
                    )
                    return {
                        "mastery_snapshot_ids": snapshot_ids,
                        "errors": existing_errors,
                    }
        consumed = list(state.get("consumed_signal_ids") or state.get("consumed_event_ids") or [])
        for update in state.get("mastery_updates", []) or []:
            for signal_id in update.get("consumed_signal_ids", []) or []:
                if signal_id not in consumed:
                    consumed.append(signal_id)
        return {
            "mastery_snapshot_ids": snapshot_ids,
            "consumed_signal_ids": consumed,
            "consumed_event_ids": consumed,
        }

    return persist_snapshots_node


def build_graph(
    *,
    learning_event_repository: LearningEventRepository | None = None,
    attempt_repository: AttemptRepository | None = None,
    mastery_repository: MasterySnapshotRepository | None = None,
) -> StateGraph:
    graph = StateGraph(MasteryEvaluationState)
    graph.add_node(
        "load_repository_inputs",
        _load_repository_inputs(
            learning_event_repository=learning_event_repository,
            attempt_repository=attempt_repository,
            mastery_repository=mastery_repository,
        ),
    )
    graph.add_node("objective_grader", objective_grader_node)
    graph.add_node("weak_signal_extractor", weak_signal_extractor_node)
    graph.add_node("evidence_aggregator", evidence_aggregator_node)
    graph.add_node("mastery_updater", mastery_updater_node)
    graph.add_node("status_classifier", status_classifier_node)
    graph.add_node("persist_snapshots", _persist_snapshots(mastery_repository))
    graph.add_node("next_action_policy", next_action_policy_node)
    graph.add_node("response_composer", response_composer_node)

    graph.set_entry_point("load_repository_inputs")
    graph.add_edge("load_repository_inputs", "objective_grader")
    graph.add_edge("objective_grader", "weak_signal_extractor")
    graph.add_edge("weak_signal_extractor", "evidence_aggregator")
    graph.add_edge("evidence_aggregator", "mastery_updater")
    graph.add_edge("mastery_updater", "status_classifier")
    graph.add_edge("status_classifier", "persist_snapshots")
    graph.add_edge("persist_snapshots", "next_action_policy")
    graph.add_edge("next_action_policy", "response_composer")
    graph.add_edge("response_composer", END)
    return graph


def build_production_graph(*, subject_id: str | None = None) -> StateGraph:
    if not is_graph_facts_enabled():
        return build_graph(
            attempt_repository=LegacyPracticeAttemptRepository(subject_id=subject_id),
            mastery_repository=LegacyKnowledgeStatsMasteryRepository(subject_id=subject_id),
        )
    repos = build_graph_fact_repositories()
    return build_graph(
        learning_event_repository=repos.learning_events,
        attempt_repository=CompositeAttemptRepository(
            primary=repos.attempts,
            legacy=LegacyPracticeAttemptRepository(subject_id=subject_id),
        ),
        mastery_repository=CompositeMasterySnapshotRepository(
            primary=repos.mastery_snapshots,
            legacy=LegacyKnowledgeStatsMasteryRepository(subject_id=subject_id),
        ),
    )
