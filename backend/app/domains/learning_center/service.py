from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import (
    GraphAttemptModel,
    GraphQuestionItemModel,
    KbChapterModel,
    KbConceptModel,
    KbSubjectModel,
    KbTopicModel,
    MasterySnapshotModel,
    PracticeAttemptModel,
    PracticeQuestionModel,
    UserKnowledgeStatModel,
)
from app.knowledge.concept_registry import ConceptNode, get_concept_registry
from app.persistence.repositories.graph_facts import is_graph_facts_enabled
from app.shared.schemas.subject import CANONICAL_SUBJECT_IDS


SessionFactory = Callable[[], AbstractContextManager[Any]]
STATUS_ORDER = {"unstarted": 0, "weak": 1, "learning": 2, "mastered": 3}


@dataclass(frozen=True)
class TaxonomyConcept:
    subject_id: str
    subject_name: str
    chapter_id: str
    chapter_name: str
    chapter_order: int
    topic_id: str
    topic_name: str
    topic_order: int
    concept_id: str
    concept_name: str
    aliases: list[str]
    prerequisites: list[str]
    importance: str
    exam_frequency: str


def get_learning_center(
    *,
    user_id: str,
    subject_id: str | None = None,
    session_factory: SessionFactory | None = None,
) -> dict[str, Any]:
    requested_subject = str(subject_id or "").strip()
    session_factory = session_factory or session_scope
    facts_enabled = is_graph_facts_enabled()
    with session_factory() as session:
        concepts = _merged_taxonomy(session, subject_id=requested_subject or None)
        if facts_enabled:
            snapshots = _snapshots_by_concept(session, user_id=user_id, subject_id=requested_subject or None)
            attempts = _attempt_stats_by_concept(session, user_id=user_id, subject_id=requested_subject or None)
            facts_source = "graph"
        else:
            snapshots = _legacy_snapshots_by_concept(session, user_id=user_id, subject_id=requested_subject or None)
            attempts = _legacy_attempt_stats_by_concept(session, user_id=user_id, subject_id=requested_subject or None)
            facts_source = "legacy_fallback"
        question_counts = _question_counts_by_concept(session, subject_id=requested_subject or None)

    subjects = _build_subjects(
        concepts,
        snapshots=snapshots,
        attempts=attempts,
        question_counts=question_counts,
    )
    next_move = _choose_next_move(subjects)
    return {
        "user_id": user_id,
        "subject_id": requested_subject or None,
        "subjects": subjects,
        "summary": _aggregate_nodes(subjects),
        "next_move": next_move,
        "facts_source": facts_source,
    }


def _merged_taxonomy(session: Any, *, subject_id: str | None) -> list[TaxonomyConcept]:
    concepts_by_id = {
        concept.concept_id: concept
        for concept in _taxonomy_from_registry(subject_id=subject_id)
    }
    for concept in _taxonomy_from_db(session, subject_id=subject_id):
        concepts_by_id[concept.concept_id] = concept
    return sorted(concepts_by_id.values(), key=_taxonomy_sort_key)


def _taxonomy_from_db(session: Any, *, subject_id: str | None) -> list[TaxonomyConcept]:
    concept_query = select(KbConceptModel)
    if subject_id:
        concept_query = concept_query.where(KbConceptModel.subject_id == subject_id)
    concept_rows = list(session.scalars(concept_query).all())
    if not concept_rows:
        return []

    subject_ids = {row.subject_id for row in concept_rows}
    chapter_ids = {row.chapter_id for row in concept_rows}
    topic_ids = {row.topic_id for row in concept_rows}
    subjects = {
        row.subject_id: row
        for row in session.scalars(select(KbSubjectModel).where(KbSubjectModel.subject_id.in_(subject_ids))).all()
    }
    chapters = {
        row.chapter_id: row
        for row in session.scalars(select(KbChapterModel).where(KbChapterModel.chapter_id.in_(chapter_ids))).all()
    }
    topics = {
        row.topic_id: row
        for row in session.scalars(select(KbTopicModel).where(KbTopicModel.topic_id.in_(topic_ids))).all()
    }
    result: list[TaxonomyConcept] = []
    for row in concept_rows:
        subject = subjects.get(row.subject_id)
        chapter = chapters.get(row.chapter_id)
        topic = topics.get(row.topic_id)
        result.append(
            TaxonomyConcept(
                subject_id=row.subject_id,
                subject_name=(subject.subject_name if subject else "") or row.subject_id,
                chapter_id=row.chapter_id,
                chapter_name=(chapter.chapter_name if chapter else "") or row.chapter_id,
                chapter_order=int(chapter.sort_order if chapter else 0),
                topic_id=row.topic_id,
                topic_name=(topic.topic_name if topic else "") or row.topic_id,
                topic_order=int(topic.sort_order if topic else 0),
                concept_id=row.concept_id,
                concept_name=row.concept_name,
                aliases=[str(item) for item in list(row.aliases_json or [])],
                prerequisites=[str(item) for item in list(row.prerequisites_json or [])],
                importance=row.importance,
                exam_frequency=row.exam_frequency,
            )
        )
    return sorted(result, key=_taxonomy_sort_key)


def _taxonomy_from_registry(*, subject_id: str | None) -> list[TaxonomyConcept]:
    registry = get_concept_registry()
    nodes: list[ConceptNode] = [
        node
        for node in registry.concepts.values()
        if not subject_id or node.subject_id == subject_id
    ]
    return sorted(
        [
            TaxonomyConcept(
                subject_id=node.subject_id,
                subject_name=node.subject_name,
                chapter_id=node.chapter_id,
                chapter_name=node.chapter_name,
                chapter_order=0,
                topic_id=node.topic_id,
                topic_name=node.topic_name,
                topic_order=0,
                concept_id=node.concept_id,
                concept_name=node.concept_name,
                aliases=list(node.aliases),
                prerequisites=list(node.prerequisites),
                importance=node.importance,
                exam_frequency=node.exam_frequency,
            )
            for node in nodes
        ],
        key=_taxonomy_sort_key,
    )


def _snapshots_by_concept(session: Any, *, user_id: str, subject_id: str | None) -> dict[str, dict[str, Any]]:
    stmt = select(MasterySnapshotModel).where(MasterySnapshotModel.user_id == user_id)
    if subject_id:
        stmt = stmt.where(MasterySnapshotModel.subject_id == subject_id)
    return {
        row.concept_id: {
            "p_mastery": float(row.p_mastery or 0.0),
            "status": str(row.status or "learning"),
            "updated_at": _iso(row.updated_at),
            "evidence_ids": list(row.evidence_ids or []),
        }
        for row in session.scalars(stmt).all()
    }


def _attempt_stats_by_concept(session: Any, *, user_id: str, subject_id: str | None) -> dict[str, dict[str, Any]]:
    stmt = select(GraphAttemptModel).where(GraphAttemptModel.user_id == user_id)
    if subject_id:
        stmt = stmt.where(GraphAttemptModel.subject_id == subject_id)
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "attempt_count": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "last_practiced_at": "",
        }
    )
    for row in session.scalars(stmt).all():
        concept_id = str(row.concept_id or "").strip()
        if not concept_id:
            continue
        item = stats[concept_id]
        item["attempt_count"] += 1
        if bool(row.is_correct):
            item["correct_count"] += 1
        else:
            item["wrong_count"] += 1
        created_at = _iso(row.created_at)
        if created_at and created_at > item["last_practiced_at"]:
            item["last_practiced_at"] = created_at
    return dict(stats)


def _legacy_snapshots_by_concept(session: Any, *, user_id: str, subject_id: str | None) -> dict[str, dict[str, Any]]:
    stmt = select(UserKnowledgeStatModel).where(UserKnowledgeStatModel.user_id == user_id)
    if subject_id:
        stmt = stmt.where(UserKnowledgeStatModel.subject_id == subject_id)
    snapshots: dict[str, dict[str, Any]] = {}
    for row in session.scalars(stmt).all():
        concept_id = resolve_legacy_concept_id(
            concept_id=row.concept_id,
            knowledge_point=row.knowledge_point,
            concept_name=row.concept_name,
            subject_id=row.subject_id or subject_id,
        )
        if not concept_id:
            continue
        score = float(row.mastery_score or 0.0)
        p_mastery = score / 100.0 if score > 1 else score
        snapshots[concept_id] = {
            "p_mastery": _bounded(p_mastery),
            "status": str(row.mastery_level or "learning"),
            "updated_at": _iso(row.updated_at),
            "evidence_ids": [],
        }
    return snapshots


def _legacy_attempt_stats_by_concept(session: Any, *, user_id: str, subject_id: str | None) -> dict[str, dict[str, Any]]:
    stmt = select(PracticeAttemptModel).where(PracticeAttemptModel.user_id == user_id)
    if subject_id:
        stmt = stmt.where(PracticeAttemptModel.subject_id == subject_id)
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "attempt_count": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "last_practiced_at": "",
        }
    )
    for row in session.scalars(stmt).all():
        concept_id = resolve_legacy_concept_id(
            concept_id=row.concept_id,
            knowledge_point=row.knowledge_point,
            concept_name=row.concept_name,
            subject_id=row.subject_id or subject_id,
        )
        if not concept_id:
            continue
        item = stats[concept_id]
        item["attempt_count"] += 1
        if bool(row.is_correct):
            item["correct_count"] += 1
        else:
            item["wrong_count"] += 1
        created_at = _iso(row.created_at)
        if created_at and created_at > item["last_practiced_at"]:
            item["last_practiced_at"] = created_at
    return dict(stats)


def _question_counts_by_concept(session: Any, *, subject_id: str | None = None) -> dict[str, int]:
    counts: Counter[str] = Counter()
    practice_stmt = select(PracticeQuestionModel)
    if subject_id:
        practice_stmt = practice_stmt.where(PracticeQuestionModel.subject_id == subject_id)
    for row in session.scalars(practice_stmt).all():
        concept_id = resolve_legacy_concept_id(
            concept_id=row.concept_id,
            knowledge_point=row.concept_name,
            concept_name=row.concept_name,
            subject_id=row.subject_id or subject_id,
        )
        if concept_id:
            counts[concept_id] += 1
    graph_stmt = select(GraphQuestionItemModel)
    if subject_id:
        graph_stmt = graph_stmt.where(GraphQuestionItemModel.subject_id == subject_id)
    for row in session.scalars(graph_stmt).all():
        concept_id = str(row.primary_concept_id or "").strip()
        if concept_id:
            counts[concept_id] += 1
    return dict(counts)


def resolve_legacy_concept_id(
    *,
    concept_id: Any = "",
    knowledge_point: Any = "",
    concept_name: Any = "",
    subject_id: Any = "",
) -> str:
    """Map legacy Chinese knowledge point rows back onto canonical taxonomy ids."""

    raw_concept_id = str(concept_id or "").strip()
    registry = get_concept_registry()
    if raw_concept_id and registry.get_concept(raw_concept_id) is not None:
        return raw_concept_id

    subject_hint = str(subject_id or "").strip()
    search_terms = _dedupe_legacy_terms([knowledge_point, concept_name, raw_concept_id])
    for term in search_terms:
        match = registry.match_query(term, subject_id=subject_hint)
        if match.status == "matched" and match.concept_id:
            return match.concept_id

    if raw_concept_id:
        return raw_concept_id
    return search_terms[0] if search_terms else ""


def _dedupe_legacy_terms(values: list[Any]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value or "").strip()
        key = _normalize_legacy_term(value)
        if not value or not key or key in seen:
            continue
        seen.add(key)
        terms.append(value)
    return terms


def _normalize_legacy_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s\-_./:：,，。;；、()（）\[\]【】{}<>《》\"'“”‘’!?！？]+", "", normalized)


def _build_subjects(
    concepts: list[TaxonomyConcept],
    *,
    snapshots: dict[str, dict[str, Any]],
    attempts: dict[str, dict[str, Any]],
    question_counts: dict[str, int],
) -> list[dict[str, Any]]:
    grouped_subjects: dict[str, dict[str, Any]] = {}
    for concept in concepts:
        subject = grouped_subjects.setdefault(
            concept.subject_id,
            {
                "subject_id": concept.subject_id,
                "subject_name": concept.subject_name,
                "chapters": {},
            },
        )
        chapters = subject["chapters"]
        chapter = chapters.setdefault(
            concept.chapter_id,
            {
                "chapter_id": concept.chapter_id,
                "chapter_name": concept.chapter_name,
                "subject_id": concept.subject_id,
                "sort_order": concept.chapter_order,
                "topics": {},
            },
        )
        topics = chapter["topics"]
        topic = topics.setdefault(
            concept.topic_id,
            {
                "topic_id": concept.topic_id,
                "topic_name": concept.topic_name,
                "subject_id": concept.subject_id,
                "chapter_id": concept.chapter_id,
                "sort_order": concept.topic_order,
                "concepts": [],
            },
        )
        snapshot = snapshots.get(concept.concept_id)
        attempt_stats = attempts.get(concept.concept_id, {})
        status = str(snapshot.get("status") if snapshot else "unstarted") or "unstarted"
        p_mastery = _bounded(float(snapshot.get("p_mastery") if snapshot else 0.0))
        attempt_count = int(attempt_stats.get("attempt_count") or 0)
        correct_count = int(attempt_stats.get("correct_count") or 0)
        wrong_count = int(attempt_stats.get("wrong_count") or 0)
        topic["concepts"].append(
            {
                "concept_id": concept.concept_id,
                "concept_name": concept.concept_name,
                "subject_id": concept.subject_id,
                "chapter_id": concept.chapter_id,
                "topic_id": concept.topic_id,
                "aliases": concept.aliases,
                "importance": concept.importance,
                "exam_frequency": concept.exam_frequency,
                "prerequisites": concept.prerequisites,
                "p_mastery": p_mastery,
                "mastery_score": round(p_mastery * 100, 2),
                "status": status if status in STATUS_ORDER else "learning",
                "tested": attempt_count > 0,
                "test_status": "tested" if attempt_count > 0 else "untested",
                "attempt_count": attempt_count,
                "correct_count": correct_count,
                "wrong_count": wrong_count,
                "question_count": int(question_counts.get(concept.concept_id) or 0),
                "last_practiced_at": str(attempt_stats.get("last_practiced_at") or ""),
                "updated_at": str(snapshot.get("updated_at") if snapshot else ""),
            }
        )

    subjects: list[dict[str, Any]] = []
    for subject in grouped_subjects.values():
        chapters = []
        for chapter in subject["chapters"].values():
            topics = []
            for topic in chapter["topics"].values():
                topic["concepts"] = sorted(topic["concepts"], key=lambda item: item["concept_id"])
                topics.append({**topic, **_aggregate_concepts(topic["concepts"])})
            topic_list = sorted(topics, key=lambda item: (item.get("sort_order", 0), item["topic_id"]))
            chapters.append({**chapter, "topics": topic_list, **_aggregate_nodes(topic_list)})
        chapter_list = sorted(chapters, key=lambda item: (item.get("sort_order", 0), item["chapter_id"]))
        subjects.append({**subject, "chapters": chapter_list, **_aggregate_nodes(chapter_list)})
    return sorted(subjects, key=lambda item: (_subject_order(item["subject_id"]), item["subject_id"]))


def _aggregate_concepts(concepts: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(concepts)
    if total == 0:
        return _empty_aggregate()
    status_counts = Counter(str(item.get("status") or "unstarted") for item in concepts)
    updated_at = max([str(item.get("updated_at") or "") for item in concepts], default="")
    practiced = total - status_counts.get("unstarted", 0)
    tested_count = sum(1 for item in concepts if bool(item.get("tested")))
    attempt_count = sum(int(item.get("attempt_count") or 0) for item in concepts)
    correct_count = sum(int(item.get("correct_count") or 0) for item in concepts)
    wrong_count = sum(int(item.get("wrong_count") or 0) for item in concepts)
    return {
        "concept_count": total,
        "mastery_score": round(sum(float(item.get("p_mastery") or 0.0) for item in concepts) / total * 100, 2),
        "coverage_ratio": round(practiced / total, 4),
        "status_counts": _status_counts(status_counts),
        "weak_count": int(status_counts.get("weak", 0)),
        "tested_count": tested_count,
        "untested_count": total - tested_count,
        "tested_ratio": round(tested_count / total, 4),
        "attempt_count": attempt_count,
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "updated_at": updated_at,
    }


def _aggregate_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not nodes:
        return _empty_aggregate()
    concept_count = sum(int(item.get("concept_count") or 0) for item in nodes)
    if concept_count == 0:
        return _empty_aggregate()
    status_counts: Counter[str] = Counter()
    weighted_mastery = 0.0
    updated_values: list[str] = []
    tested_count = 0
    attempt_count = 0
    correct_count = 0
    wrong_count = 0
    for item in nodes:
        count = int(item.get("concept_count") or 0)
        weighted_mastery += float(item.get("mastery_score") or 0.0) * count
        status_counts.update(dict(item.get("status_counts") or {}))
        tested_count += int(item.get("tested_count") or 0)
        attempt_count += int(item.get("attempt_count") or 0)
        correct_count += int(item.get("correct_count") or 0)
        wrong_count += int(item.get("wrong_count") or 0)
        if item.get("updated_at"):
            updated_values.append(str(item["updated_at"]))
    practiced = concept_count - status_counts.get("unstarted", 0)
    return {
        "concept_count": concept_count,
        "mastery_score": round(weighted_mastery / concept_count, 2),
        "coverage_ratio": round(practiced / concept_count, 4),
        "status_counts": _status_counts(status_counts),
        "weak_count": int(status_counts.get("weak", 0)),
        "tested_count": tested_count,
        "untested_count": concept_count - tested_count,
        "tested_ratio": round(tested_count / concept_count, 4),
        "attempt_count": attempt_count,
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "updated_at": max(updated_values, default=""),
    }


def _choose_next_move(subjects: list[dict[str, Any]]) -> dict[str, Any]:
    concepts = [
        {**concept, "subject_id": subject["subject_id"], "subject_name": subject["subject_name"]}
        for subject in subjects
        for chapter in subject.get("chapters", [])
        for topic in chapter.get("topics", [])
        for concept in topic.get("concepts", [])
    ]
    practiced_weak = [item for item in concepts if item["status"] == "weak" and item["attempt_count"] > 0]
    learning = [item for item in concepts if item["status"] == "learning"]
    important_unstarted = [
        item
        for item in concepts
        if item["status"] == "unstarted" and (item["importance"] == "high" or item["exam_frequency"] == "high")
    ]
    if practiced_weak:
        target = sorted(practiced_weak, key=lambda item: (item["p_mastery"], -item["wrong_count"], item["concept_id"]))[0]
        return _next_move(target, "review_and_practice", f"优先回到「{target['concept_name']}」复盘，再刷一组题把正确率拉上来。")
    if learning:
        target = sorted(learning, key=lambda item: (item["p_mastery"], item["concept_id"]))[0]
        return _next_move(target, "practice_variant", f"「{target['concept_name']}」正在学习中，适合马上做一组变式题巩固。")
    if important_unstarted:
        target = sorted(important_unstarted, key=lambda item: (item["importance"] != "high", item["exam_frequency"] != "high", item["concept_id"]))[0]
        return _next_move(target, "start_high_value_concept", f"可以开始高频知识点「{target['concept_name']}」，先问答理解再做题。")
    if concepts:
        target = concepts[0]
        return _next_move(target, "continue_learning", f"继续围绕「{target['concept_name']}」推进学习。")
    return {}


def _next_move(concept: dict[str, Any], action_type: str, reason: str) -> dict[str, Any]:
    return {
        "subject_id": concept["subject_id"],
        "subject_name": concept["subject_name"],
        "concept_id": concept["concept_id"],
        "concept_name": concept["concept_name"],
        "chapter_id": concept.get("chapter_id", ""),
        "topic_id": concept.get("topic_id", ""),
        "action": _next_move_action(action_type),
        "action_type": action_type,
        "reason": reason,
    }


def _next_move_action(action_type: str) -> str:
    return {
        "review_and_practice": "review_weak",
        "practice_variant": "practice_learning",
        "start_high_value_concept": "start_high_value",
        "continue_learning": "none",
    }.get(action_type, "none")


def _status_counts(counter: Counter[str] | dict[str, int]) -> dict[str, int]:
    return {status: int(counter.get(status, 0)) for status in ("unstarted", "weak", "learning", "mastered")}


def _empty_aggregate() -> dict[str, Any]:
    return {
        "concept_count": 0,
        "mastery_score": 0.0,
        "coverage_ratio": 0.0,
        "status_counts": _status_counts({}),
        "weak_count": 0,
        "tested_count": 0,
        "untested_count": 0,
        "tested_ratio": 0.0,
        "attempt_count": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "updated_at": "",
    }


def _taxonomy_sort_key(item: TaxonomyConcept) -> tuple[int, str, int, str, int, str, str]:
    return (
        _subject_order(item.subject_id),
        item.subject_id,
        item.chapter_order,
        item.chapter_id,
        item.topic_order,
        item.topic_id,
        item.concept_id,
    )


def _subject_order(subject_id: str) -> int:
    try:
        return list(CANONICAL_SUBJECT_IDS).index(subject_id)
    except ValueError:
        return len(CANONICAL_SUBJECT_IDS)


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _iso(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


__all__ = ["get_learning_center", "resolve_legacy_concept_id"]
