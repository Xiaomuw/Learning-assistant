from __future__ import annotations

import argparse
import hashlib
import json
import re
from contextlib import AbstractContextManager
from typing import Any, Callable

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from sqlalchemy import select

load_dotenv()

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import (
    GraphAttemptModel,
    GraphConceptModel,
    GraphQuestionItemModel,
    MasterySnapshotModel,
    PracticeAttemptModel,
    QuestionBankItemModel,
    UserKnowledgeStatModel,
)
from app.persistence.repositories.graph_facts import (
    SqlAttemptRepository,
    SqlConceptRepository,
    SqlMasterySnapshotRepository,
    SqlQuestionItemRepository,
)


SessionFactory = Callable[[], AbstractContextManager[Any]]


class BackfillResult(BaseModel):
    dry_run: bool = True
    dry_run_count: int = 0
    inserted_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    table_counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    def add_operation(self, *, table: str, dry_run: bool, inserted: bool = False, skipped: bool = False) -> None:
        self.table_counts[table] = self.table_counts.get(table, 0) + 1
        if dry_run:
            self.dry_run_count += 1
        elif inserted:
            self.inserted_count += 1
        elif skipped:
            self.skipped_count += 1


def backfill_graph_facts(
    *,
    execute: bool = False,
    session_factory: SessionFactory = session_scope,
) -> BackfillResult:
    result = BackfillResult(dry_run=not execute)
    attempt_repo = SqlAttemptRepository(session_factory=session_factory)
    mastery_repo = SqlMasterySnapshotRepository(session_factory=session_factory)
    question_repo = SqlQuestionItemRepository(session_factory=session_factory)
    concept_repo = SqlConceptRepository(session_factory=session_factory)

    with session_factory() as session:
        attempts = list(session.scalars(select(PracticeAttemptModel)).all())
        mastery_rows = list(session.scalars(select(UserKnowledgeStatModel)).all())
        question_rows = list(session.scalars(select(QuestionBankItemModel)).all())

    for row in attempts:
        concept_id = _stable_concept_id(row.knowledge_point)
        _upsert_concept(
            result=result,
            execute=execute,
            repo=concept_repo,
            session_factory=session_factory,
            concept_id=concept_id,
            name=row.knowledge_point or concept_id,
            subject_id=row.subject_id,
            source="legacy_practice_attempt",
        )
        _write_if_missing(
            result=result,
            execute=execute,
            table="attempts",
            exists=lambda item_id=_stable_record_id("legacy-practice", row.id): _exists(
                session_factory, GraphAttemptModel, item_id
            ),
            write=lambda item=row, item_id=_stable_record_id("legacy-practice", row.id), cid=concept_id: attempt_repo.create_attempt(
                {
                    "id": item_id,
                    "user_id": item.user_id,
                    "subject_id": item.subject_id,
                    "concept_id": cid,
                    "knowledge_point": item.knowledge_point,
                    "question_id": item.question_id,
                    "score": 1.0 if item.is_correct else 0.0,
                    "is_correct": bool(item.is_correct),
                    "created_at": item.created_at,
                    "payload": {
                        "legacy_source_table": "practice_attempts",
                        "legacy_id": item.id,
                        "session_id": item.session_id,
                        "selected_option": item.selected_option,
                        "source_type": item.source_type,
                        "question_snapshot": item.question_snapshot,
                    },
                }
            ),
        )

    for row in mastery_rows:
        concept_id = _stable_concept_id(row.knowledge_point)
        _upsert_concept(
            result=result,
            execute=execute,
            repo=concept_repo,
            session_factory=session_factory,
            concept_id=concept_id,
            name=row.knowledge_point or concept_id,
            subject_id=row.subject_id,
            source="legacy_knowledge_stats",
        )
        snapshot_id = _stable_record_id("legacy-knowledge", row.user_id, row.subject_id, concept_id)
        _write_if_missing(
            result=result,
            execute=execute,
            table="mastery_snapshots",
            exists=lambda item_id=snapshot_id: _exists(session_factory, MasterySnapshotModel, item_id),
            write=lambda item=row, item_id=snapshot_id, cid=concept_id: mastery_repo.upsert_snapshot(
                {
                    "id": item_id,
                    "user_id": item.user_id,
                    "subject_id": item.subject_id,
                    "concept_id": cid,
                    "p_mastery": _score_to_probability(item.mastery_score),
                    "status": item.mastery_level or "learning",
                    "evidence_ids": [],
                    "updated_at": item.updated_at,
                    "payload": {
                        "legacy_source_table": "user_knowledge_stats",
                        "knowledge_point": item.knowledge_point,
                        "mastery_score": item.mastery_score,
                        "exposure_count": item.exposure_count,
                        "attempt_count": item.attempt_count,
                        "correct_count": item.correct_count,
                        "wrong_count": item.wrong_count,
                        "last_seen_at": str(item.last_seen_at or ""),
                        "last_practiced_at": str(item.last_practiced_at or ""),
                    },
                }
            ),
        )

    for row in question_rows:
        concept_id = _stable_concept_id(row.knowledge_point)
        _upsert_concept(
            result=result,
            execute=execute,
            repo=concept_repo,
            session_factory=session_factory,
            concept_id=concept_id,
            name=row.knowledge_point or concept_id,
            subject_id=row.subject_id,
            source="legacy_question_bank",
        )
        question_id = _stable_record_id("legacy-question", row.id)
        _write_if_missing(
            result=result,
            execute=execute,
            table="question_items",
            exists=lambda item_id=question_id: _exists(session_factory, GraphQuestionItemModel, item_id),
            write=lambda item=row, item_id=question_id, cid=concept_id: question_repo.create_question_item(
                {
                    "id": item_id,
                    "subject_id": item.subject_id,
                    "primary_concept_id": cid,
                    "stem": item.stem,
                    "options": list(item.options_json or []),
                    "difficulty": item.difficulty or "基础",
                    "source_refs": [
                        {
                            "source_type": "legacy_question_bank",
                            "source_id": item.id,
                            "title": item.source_name,
                        }
                    ],
                    "answer_key": {
                        "correct_option": item.correct_option,
                        "correct_option_text": _correct_option_text(item.options_json, item.correct_option),
                        "explanation": item.explanation or "旧题库迁移题目。",
                        "option_rationales": dict(item.option_rationales_json or {}),
                    },
                    "rubric": {
                        "criteria": ["single_correct_option"],
                        "full_credit": "选择唯一正确选项并理解解析。",
                        "common_misconceptions": [],
                    },
                    "quality_report": {
                        "passed": True,
                        "issues": [],
                        "checked_count": 1,
                        "expected_count": 1,
                        "reviewer": {"source": "backfill"},
                    },
                    "generation_source": "legacy_question_bank_backfill",
                    "metadata": {
                        "legacy_source_table": "question_bank_items",
                        "legacy_id": item.id,
                        "source_year": item.source_year,
                        "tags": list(item.tags_json or []),
                    },
                }
            ),
        )

    return result


def _write_if_missing(
    *,
    result: BackfillResult,
    execute: bool,
    table: str,
    exists,
    write,
) -> None:
    try:
        already_exists = bool(exists())
        if not execute:
            result.add_operation(table=table, dry_run=True)
            return
        if already_exists:
            result.add_operation(table=table, dry_run=False, skipped=True)
            return
        write()
        result.add_operation(table=table, dry_run=False, inserted=True)
    except Exception as exc:
        result.error_count += 1
        detail = str(exc).replace("\n", " ")[:240]
        result.errors.append(f"{table}:{exc.__class__.__name__}:{detail}")


def _upsert_concept(
    *,
    result: BackfillResult,
    execute: bool,
    repo: SqlConceptRepository,
    session_factory: SessionFactory,
    concept_id: str,
    name: str,
    subject_id: str,
    source: str,
) -> None:
    _write_if_missing(
        result=result,
        execute=execute,
        table="concepts",
        exists=lambda: _exists(session_factory, GraphConceptModel, concept_id),
        write=lambda: repo.upsert_concept(
            {
                "concept_id": concept_id,
                "name": name,
                "subject_id": subject_id,
                "source": source,
                "metadata": {"backfilled": True},
            }
        ),
    )


def _exists(session_factory: SessionFactory, model: type[Any], primary_key: str) -> bool:
    with session_factory() as session:
        return session.get(model, primary_key) is not None


def _stable_concept_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", str(value or "").strip().lower())
    normalized = normalized.strip("-_")[:120]
    return normalized or "general"


def _stable_record_id(prefix: str, *parts: Any, max_length: int = 100) -> str:
    raw = "-".join([str(prefix), *[str(part or "") for part in parts]])
    if raw.strip() and len(raw) <= max_length:
        return raw
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", raw.strip().lower())
    normalized = normalized.strip("-_")
    if not normalized:
        normalized = str(prefix)
    if len(normalized) <= max_length:
        return normalized
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    head = normalized[: max_length - len(digest) - 1].rstrip("-_")
    return f"{head}-{digest}"


def _score_to_probability(value: Any) -> float:
    try:
        score = float(value or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    if score > 1.0:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def _correct_option_text(options: Any, correct_option: str) -> str:
    for option in list(options or []):
        if isinstance(option, dict) and str(option.get("key") or "") == correct_option:
            return str(option.get("text") or "")
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill legacy learning facts into graph-era facts tables.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Write changes. Defaults to dry-run.")
    mode.add_argument("--dry-run", action="store_true", help="Only count planned changes without writing.")
    args = parser.parse_args(argv)
    result = backfill_graph_facts(execute=bool(args.execute))
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 1 if result.error_count else 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
