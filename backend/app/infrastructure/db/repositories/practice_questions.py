from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import (
    KbChapterModel,
    KbConceptModel,
    KbSubjectModel,
    KbTopicModel,
    PracticeQuestionModel,
)
from app.infrastructure.db.repositories._shared import utcnow


VALID_OPTION_KEYS = ("A", "B", "C", "D")
VALID_DIFFICULTIES = {"basic", "medium", "hard"}
DIFFICULTY_ALIASES = {
    "basic": "basic",
    "medium": "medium",
    "hard": "hard",
    "基础": "basic",
    "变式": "medium",
    "易错": "hard",
}
OnConflict = Literal["skip", "upsert"]


@dataclass(frozen=True)
class PracticeQuestionValidationIssue:
    index: int
    question_id: str
    field: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "question_id": self.question_id,
            "field": self.field,
            "message": self.message,
        }


@dataclass
class PracticeQuestionValidationResult:
    questions: list[dict[str, Any]] = field(default_factory=list)
    issues: list[PracticeQuestionValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues

    def raise_for_errors(self) -> None:
        if self.issues:
            raise PracticeQuestionValidationError(self.issues)


@dataclass(frozen=True)
class PracticeQuestionImportResult:
    total: int
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
        }


class PracticeQuestionValidationError(ValueError):
    def __init__(self, issues: list[PracticeQuestionValidationIssue]) -> None:
        self.issues = issues
        preview = "; ".join(
            f"第 {issue.index} 条 {issue.field}: {issue.message}"
            for issue in issues[:5]
        )
        suffix = f"；另有 {len(issues) - 5} 个错误" if len(issues) > 5 else ""
        super().__init__(f"题库校验失败：{preview}{suffix}")


def load_practice_question_json(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [_dict_item(item, index=index) for index, item in enumerate(payload, start=1)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [_dict_item(item, index=index) for index, item in enumerate(payload["items"], start=1)]
    raise ValueError("题库 JSON 必须是数组，或形如 {\"items\": [...]} 的对象。")


def validate_practice_questions(
    raw_items: list[dict[str, Any]],
    *,
    source_file: str = "",
) -> PracticeQuestionValidationResult:
    result = PracticeQuestionValidationResult()
    seen_question_ids: dict[str, int] = {}
    concept_ids = {
        _text(item.get("concept_id"))
        for item in raw_items
        if _text(item.get("concept_id"))
    }

    with session_scope() as session:
        concept_rows = {
            row.concept_id: row
            for row in session.scalars(
                select(KbConceptModel).where(KbConceptModel.concept_id.in_(concept_ids))
            ).all()
        } if concept_ids else {}

        for index, raw in enumerate(raw_items, start=1):
            row_issues: list[PracticeQuestionValidationIssue] = []
            question_id = _text(raw.get("question_id"))

            def add_issue(field: str, message: str) -> None:
                row_issues.append(
                    PracticeQuestionValidationIssue(
                        index=index,
                        question_id=question_id,
                        field=field,
                        message=message,
                    )
                )

            if not question_id:
                add_issue("question_id", "不能为空")
            elif question_id in seen_question_ids:
                add_issue(
                    "question_id",
                    f"与第 {seen_question_ids[question_id]} 条重复",
                )
            else:
                seen_question_ids[question_id] = index

            stem = _text(raw.get("stem"))
            if not stem:
                add_issue("stem", "不能为空")

            explanation = _text(raw.get("explanation"))
            if not explanation:
                add_issue("explanation", "不能为空")

            answer = _text(raw.get("answer")).upper()
            if answer not in VALID_OPTION_KEYS:
                add_issue("answer", "必须属于 A/B/C/D")

            difficulty = normalize_difficulty(raw.get("difficulty"))
            if not difficulty:
                add_issue("difficulty", "必须属于 basic/medium/hard，或基础/变式/易错")

            options, option_error = normalize_options(raw.get("options"))
            if option_error:
                add_issue("options", option_error)

            concept_id = _text(raw.get("concept_id"))
            concept = concept_rows.get(concept_id)
            if not concept_id:
                add_issue("concept_id", "不能为空")
            elif concept is None:
                add_issue("concept_id", f"不存在于 kb_concept: {concept_id}")

            result.issues.extend(row_issues)
            if row_issues or concept is None or not difficulty:
                continue

            canonical = _canonical_metadata(session, concept)
            result.questions.append(
                {
                    "question_id": question_id,
                    "subject_id": canonical["subject_id"],
                    "subject_name": canonical["subject_name"],
                    "chapter_name": canonical["chapter_name"],
                    "topic_name": canonical["topic_name"],
                    "concept_id": concept.concept_id,
                    "concept_name": canonical["concept_name"],
                    "difficulty": difficulty,
                    "stem": stem,
                    "options": options,
                    "answer": answer,
                    "explanation": explanation,
                    "knowledge_points": _normalize_string_list(raw.get("knowledge_points")) or [canonical["concept_name"]],
                    "common_trap": _text(raw.get("common_trap")),
                    "metadata": _metadata_for_raw(raw, canonical=canonical),
                    "source_file": source_file,
                }
            )

    return result


def import_practice_questions(
    raw_items: list[dict[str, Any]],
    *,
    on_conflict: OnConflict = "skip",
    source_file: str = "",
) -> PracticeQuestionImportResult:
    if on_conflict not in {"skip", "upsert"}:
        raise ValueError("on_conflict 必须是 skip 或 upsert")

    validation = validate_practice_questions(raw_items, source_file=source_file)
    validation.raise_for_errors()

    inserted = 0
    updated = 0
    skipped = 0
    with session_scope() as session:
        for item in validation.questions:
            row = session.get(PracticeQuestionModel, item["question_id"])
            if row is not None and on_conflict == "skip":
                skipped += 1
                continue
            if row is None:
                row = PracticeQuestionModel(question_id=item["question_id"])
                session.add(row)
                inserted += 1
            else:
                updated += 1
            _assign_practice_question(row, item)
        session.flush()

    return PracticeQuestionImportResult(
        total=len(validation.questions),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
    )


def get_practice_question(question_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.get(PracticeQuestionModel, question_id)
        if row is None:
            return None
        return serialize_practice_question(row)


def serialize_practice_question(row: PracticeQuestionModel) -> dict[str, Any]:
    return {
        "question_id": row.question_id,
        "subject_id": row.subject_id,
        "subject_name": row.subject_name,
        "chapter_name": row.chapter_name,
        "topic_name": row.topic_name,
        "concept_id": row.concept_id,
        "concept_name": row.concept_name,
        "difficulty": row.difficulty,
        "stem": row.stem,
        "options": dict(row.options_json or {}),
        "answer": row.answer,
        "explanation": row.explanation,
        "knowledge_points": list(row.knowledge_points_json or []),
        "common_trap": row.common_trap,
        "metadata": dict(row.metadata_json or {}),
        "source_file": row.source_file,
    }


def normalize_difficulty(value: Any) -> str:
    normalized = _text(value)
    return DIFFICULTY_ALIASES.get(normalized, "")


def normalize_options(value: Any) -> tuple[dict[str, str], str]:
    raw_options: dict[str, Any] = {}
    if isinstance(value, dict):
        raw_options = dict(value)
    elif isinstance(value, list):
        for option in value:
            if not isinstance(option, dict):
                continue
            key = _text(option.get("key") or option.get("label")).upper()
            if key:
                raw_options[key] = option.get("text") or option.get("value") or ""
    else:
        return {}, "必须是包含 A/B/C/D 的对象，或包含 key/text 的数组"

    normalized = {
        key: _text(raw_options.get(key))
        for key in VALID_OPTION_KEYS
    }
    missing = [key for key, text in normalized.items() if not text]
    extra = sorted(
        key
        for key in raw_options
        if str(key).strip().upper() not in VALID_OPTION_KEYS
    )
    if missing:
        return normalized, f"缺少或为空的选项: {', '.join(missing)}"
    if extra:
        return normalized, f"存在非法选项键: {', '.join(extra)}"
    return normalized, ""


def _assign_practice_question(row: PracticeQuestionModel, item: dict[str, Any]) -> None:
    row.subject_id = item["subject_id"]
    row.subject_name = item["subject_name"]
    row.chapter_name = item["chapter_name"]
    row.topic_name = item["topic_name"]
    row.concept_id = item["concept_id"]
    row.concept_name = item["concept_name"]
    row.difficulty = item["difficulty"]
    row.stem = item["stem"]
    row.options_json = dict(item["options"])
    row.answer = item["answer"]
    row.explanation = item["explanation"]
    row.knowledge_points_json = list(item["knowledge_points"])
    row.common_trap = item["common_trap"]
    row.metadata_json = dict(item["metadata"])
    row.source_file = item["source_file"]
    row.updated_at = utcnow()


def _canonical_metadata(session, concept: KbConceptModel) -> dict[str, str]:
    subject = session.get(KbSubjectModel, concept.subject_id)
    chapter = session.get(KbChapterModel, concept.chapter_id)
    topic = session.get(KbTopicModel, concept.topic_id)
    metadata = dict(concept.metadata_json or {})
    return {
        "subject_id": concept.subject_id,
        "subject_name": (subject.subject_name if subject else "") or str(metadata.get("subject_name") or ""),
        "chapter_id": concept.chapter_id,
        "chapter_name": (chapter.chapter_name if chapter else "") or str(metadata.get("chapter_name") or ""),
        "topic_id": concept.topic_id,
        "topic_name": (topic.topic_name if topic else "") or str(metadata.get("topic_name") or ""),
        "concept_id": concept.concept_id,
        "concept_name": concept.concept_name,
    }


def _metadata_for_raw(raw: dict[str, Any], *, canonical: dict[str, str]) -> dict[str, Any]:
    declared = {
        key: _text(raw.get(key))
        for key in ("subject_name", "chapter_name", "topic_name", "concept_name")
        if _text(raw.get(key))
    }
    return {
        "declared": declared,
        "canonical": dict(canonical),
    }


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("；", ";").replace("，", ",").replace(";", ",").split(",") if item.strip()]
    return []


def _dict_item(item: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"第 {index} 条题目必须是 JSON 对象。")
    return dict(item)


def _text(value: Any) -> str:
    return str(value or "").strip()
