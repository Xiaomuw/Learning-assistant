from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, or_, select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import (
    KbChapterModel,
    KbChunkModel,
    KbConceptModel,
    KbSubjectModel,
    KbTopicModel,
)
from app.infrastructure.db.repositories._shared import utcnow
from app.knowledge.concept_registry import ConceptNode, ConceptRegistry, get_concept_registry


def sync_knowledge_taxonomy(registry: ConceptRegistry | None = None) -> int:
    """Materialize the YAML taxonomy into relational lookup tables."""

    registry = registry or get_concept_registry()
    written = 0
    with session_scope() as session:
        for subject in registry.subjects.values():
            row = session.get(KbSubjectModel, subject["subject_id"])
            if row is None:
                row = KbSubjectModel(subject_id=subject["subject_id"])
                session.add(row)
                written += 1
            row.subject_name = str(subject.get("subject_name") or "")
            row.metadata_json = {
                "source_file": subject.get("source_file") or "",
                "registry_source": "yaml",
            }
            row.updated_at = utcnow()

        # Alembic owns the FK constraints, while these ORM models intentionally
        # do not define relationships. Flush parent subjects before child rows
        # so PostgreSQL never sees kb_chapter/kb_topic/kb_concept first.
        session.flush()

        nodes = list(registry.list_candidates(limit=10_000))

        chapter_seen: set[str] = set()
        topic_seen: set[str] = set()
        chapter_nodes: list[tuple[int, ConceptNode]] = []
        topic_nodes: list[tuple[int, ConceptNode]] = []
        for index, node in enumerate(nodes, start=1):
            if node.chapter_id not in chapter_seen:
                chapter_nodes.append((index, node))
                chapter_seen.add(node.chapter_id)
            if node.topic_id not in topic_seen:
                topic_nodes.append((index, node))
                topic_seen.add(node.topic_id)

        for index, node in chapter_nodes:
            _upsert_chapter(session, node=node, sort_order=index)
            written += 1
        session.flush()

        for index, node in topic_nodes:
            _upsert_topic(session, node=node, sort_order=index)
            written += 1
        session.flush()

        for node in nodes:
            _upsert_concept(session, node=node)
            written += 1
        session.flush()
    return written


def save_kb_chunk_record(payload: dict[str, Any]) -> str:
    """Upsert one chunk mapping record, including unmapped chunks."""

    record_id = str(payload.get("id") or payload.get("vector_id") or uuid.uuid4())
    with session_scope() as session:
        row = session.get(KbChunkModel, record_id)
        if row is None:
            row = KbChunkModel(id=record_id)
            session.add(row)
        row.vector_id = str(payload.get("vector_id") or "")
        row.subject_id = str(payload.get("subject_id") or "")
        row.subject_name = str(payload.get("subject_name") or "")
        row.chapter_id = str(payload.get("chapter_id") or "")
        row.chapter_name = str(payload.get("chapter_name") or "")
        row.topic_id = str(payload.get("topic_id") or "")
        row.topic_name = str(payload.get("topic_name") or "")
        row.concept_id = str(payload.get("concept_id") or "")
        row.concept_name = str(payload.get("concept_name") or "")
        row.source_file = str(payload.get("source_file") or payload.get("source") or "")
        row.page_start = _optional_int(payload.get("page_start"))
        row.page_end = _optional_int(payload.get("page_end"))
        row.mapping_status = str(payload.get("mapping_status") or "unmapped")
        row.content_hash = str(payload.get("content_hash") or "")
        row.content_text = str(payload.get("content_text") or "")
        row.metadata_json = dict(payload.get("metadata_json") or payload.get("metadata") or {})
        row.updated_at = utcnow()
        session.flush()
    return record_id


def delete_kb_chunks_by_source(
    *,
    subject_id: str | None,
    source_file: str,
    source_id: str | None = None,
    doc_type: str | None = None,
    user_id: str | None = None,
) -> int:
    if not source_file:
        return 0
    with session_scope() as session:
        stmt = delete(KbChunkModel).where(KbChunkModel.source_file == source_file)
        if subject_id:
            stmt = stmt.where(KbChunkModel.subject_id == subject_id)
        if source_id is not None:
            stmt = stmt.where(KbChunkModel.metadata_json["source_id"].as_string() == str(source_id))
        if doc_type is not None:
            stmt = stmt.where(KbChunkModel.metadata_json["doc_type"].as_string() == str(doc_type))
        owner = KbChunkModel.metadata_json["user_id"].as_string()
        if user_id:
            stmt = stmt.where(owner == str(user_id))
        else:
            # Shared-source replacement must not delete personal mappings.
            stmt = stmt.where(or_(owner.is_(None), owner == ""))
        result = session.execute(stmt)
        session.flush()
        return int(result.rowcount or 0)


def list_unmapped_chunks(*, subject_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = select(KbChunkModel).where(KbChunkModel.mapping_status == "unmapped")
        if subject_id:
            stmt = stmt.where(KbChunkModel.subject_id == subject_id)
        stmt = stmt.order_by(KbChunkModel.updated_at.desc()).limit(max(1, min(int(limit or 100), 500)))
        rows = session.scalars(stmt).all()
        return [_chunk_payload(row) for row in rows]


def _upsert_chapter(session, *, node: ConceptNode, sort_order: int) -> None:
    row = session.get(KbChapterModel, node.chapter_id)
    if row is None:
        row = KbChapterModel(chapter_id=node.chapter_id)
        session.add(row)
    row.subject_id = node.subject_id
    row.chapter_name = node.chapter_name
    row.sort_order = sort_order
    row.metadata_json = {"subject_name": node.subject_name}
    row.updated_at = utcnow()


def _upsert_topic(session, *, node: ConceptNode, sort_order: int) -> None:
    row = session.get(KbTopicModel, node.topic_id)
    if row is None:
        row = KbTopicModel(topic_id=node.topic_id)
        session.add(row)
    row.subject_id = node.subject_id
    row.chapter_id = node.chapter_id
    row.topic_name = node.topic_name
    row.sort_order = sort_order
    row.metadata_json = {
        "subject_name": node.subject_name,
        "chapter_name": node.chapter_name,
    }
    row.updated_at = utcnow()


def _upsert_concept(session, *, node: ConceptNode) -> None:
    row = session.get(KbConceptModel, node.concept_id)
    if row is None:
        row = KbConceptModel(concept_id=node.concept_id)
        session.add(row)
    row.subject_id = node.subject_id
    row.chapter_id = node.chapter_id
    row.topic_id = node.topic_id
    row.concept_name = node.concept_name
    row.aliases_json = list(node.aliases)
    row.prerequisites_json = list(node.prerequisites)
    row.importance = node.importance
    row.exam_frequency = node.exam_frequency
    row.question_types_json = list(node.question_types)
    row.metadata_json = {
        "subject_name": node.subject_name,
        "chapter_name": node.chapter_name,
        "topic_name": node.topic_name,
    }
    row.updated_at = utcnow()


def _chunk_payload(row: KbChunkModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "vector_id": row.vector_id,
        "subject_id": row.subject_id,
        "subject_name": row.subject_name,
        "chapter_id": row.chapter_id,
        "chapter_name": row.chapter_name,
        "topic_id": row.topic_id,
        "topic_name": row.topic_name,
        "concept_id": row.concept_id,
        "concept_name": row.concept_name,
        "source_file": row.source_file,
        "page_start": row.page_start,
        "page_end": row.page_end,
        "mapping_status": row.mapping_status,
        "content_hash": row.content_hash,
        "content_text": row.content_text,
        "metadata_json": dict(row.metadata_json or {}),
    }


def _optional_int(value: Any) -> int | None:
    try:
        if value in {None, ""}:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
