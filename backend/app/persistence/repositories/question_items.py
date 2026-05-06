from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.infrastructure.db.repositories.practice import (
    list_question_bank_item_records,
    upsert_question_bank_item_records,
)
from app.persistence.interfaces import QuestionItemRepository


@dataclass(frozen=True)
class LegacyQuestionBankItemRepository(QuestionItemRepository):
    """Adapter from the graph-era QuestionItemRepository to the legacy bank.

    The graph depends only on ``QuestionItemRepository``. This adapter is the
    explicit boundary that maps new ``QuestionItem`` payloads into the existing
    ``question_bank_items`` persistence functions.
    """

    subject_id: str = "general"
    source_name: str = "qgen_graph"

    def create_question_item(self, payload: dict[str, Any]) -> str:
        item_id = str(payload.get("id") or f"qgen-{uuid4()}")
        upsert_question_bank_item_records(
            [
                _question_item_payload_to_legacy_record(
                    payload,
                    item_id=item_id,
                    subject_id=self.subject_id,
                    source_name=self.source_name,
                )
            ]
        )
        return item_id

    def find_similar(self, payload: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
        stem = _normalize_text(str(payload.get("stem") or payload.get("question") or ""))
        concept_id = str(payload.get("primary_concept_id") or payload.get("knowledge_point") or "").strip()
        difficulty = str(payload.get("difficulty") or "").strip() or None
        records = list_question_bank_item_records(
            subject_id=self.subject_id,
            knowledge_points=[concept_id] if concept_id else None,
            difficulty=difficulty,
            limit=max(limit * 3, limit),
        )
        matches: list[dict[str, Any]] = []
        for record in records:
            candidate = record.model_dump(mode="json")
            if stem and _normalize_text(candidate.get("question", "")) != stem:
                continue
            matches.append(
                {
                    "id": candidate.get("id") or candidate.get("question_id"),
                    "question_id": candidate.get("question_id") or candidate.get("id"),
                    "stem": candidate.get("question", ""),
                    "primary_concept_id": candidate.get("knowledge_point", ""),
                    "difficulty": candidate.get("difficulty", ""),
                    "source_type": candidate.get("source_type", "question_bank"),
                    "source_name": candidate.get("source_name", ""),
                }
            )
            if len(matches) >= limit:
                break
        return matches


def _question_item_payload_to_legacy_record(
    payload: dict[str, Any],
    *,
    item_id: str,
    subject_id: str,
    source_name: str,
) -> dict[str, Any]:
    answer_key = payload.get("answer_key") if isinstance(payload.get("answer_key"), dict) else {}
    rubric = payload.get("rubric") if isinstance(payload.get("rubric"), dict) else {}
    source_refs = list(payload.get("source_refs") or [])
    first_source = source_refs[0] if source_refs and isinstance(source_refs[0], dict) else {}
    tags = [
        str(item).strip()
        for item in [
            payload.get("primary_concept_id"),
            payload.get("generation_source"),
            first_source.get("source_type"),
        ]
        if str(item or "").strip()
    ]
    common_misconceptions = [
        str(item).strip()
        for item in list(rubric.get("common_misconceptions") or [])
        if str(item or "").strip()
    ]
    return {
        "id": item_id,
        "question_id": item_id,
        "subject_id": subject_id,
        "knowledge_point": str(payload.get("primary_concept_id") or "").strip(),
        "question": str(payload.get("stem") or "").strip(),
        "options": list(payload.get("options") or []),
        "correct_option": str(answer_key.get("correct_option") or "A").strip().upper()[:1],
        "explanation": str(answer_key.get("explanation") or "").strip(),
        "option_rationales": dict(answer_key.get("option_rationales") or {}),
        "difficulty": str(payload.get("difficulty") or "基础").strip() or "基础",
        "source_type": str(first_source.get("source_type") or "qgen_graph").strip(),
        "source_name": str(first_source.get("title") or source_name).strip(),
        "source_year": None,
        "hint": "；".join(common_misconceptions[:2]),
        "tags": tags,
    }


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()
