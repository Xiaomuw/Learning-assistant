"""
Backfill graph-era mastery snapshots from legacy practice attempts.

用法：
  python scripts/backfill_mastery_snapshots.py --dry-run
  python scripts/backfill_mastery_snapshots.py --user-id default_user
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.practice.attempts import _graph_attempt_id_for_practice_attempt
from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import GraphAttemptModel, PracticeAttemptModel
from app.infrastructure.db.repositories.bootstrap import init_database
from app.knowledge.concept_registry import get_concept_registry
from app.orchestration.graphs.mastery.graph import build_graph as build_mastery_graph
from app.persistence.repositories.graph_facts import build_graph_fact_repositories


def backfill(*, user_id: str | None = None, subject_id: str | None = None, limit: int = 0, dry_run: bool = False) -> dict[str, Any]:
    rows = _legacy_attempts(user_id=user_id, subject_id=subject_id, limit=limit)
    registry = get_concept_registry()
    repos = build_graph_fact_repositories()
    graph = build_mastery_graph(
        learning_event_repository=repos.learning_events,
        attempt_repository=None,
        mastery_repository=repos.mastery_snapshots,
    ).compile()

    result = {
        "total": len(rows),
        "backfilled": 0,
        "skipped_existing": 0,
        "skipped_unmapped": 0,
        "dry_run": dry_run,
    }
    for attempt in rows:
        concept = registry.get_concept(str(attempt.concept_id or ""))
        if concept is None:
            result["skipped_unmapped"] += 1
            continue
        graph_attempt_id = _graph_attempt_id_for_practice_attempt(attempt.id)
        if _graph_attempt_exists(graph_attempt_id):
            result["skipped_existing"] += 1
            continue
        payload = {
            "id": graph_attempt_id,
            "attempt_id": graph_attempt_id,
            "user_id": attempt.user_id,
            "subject_id": attempt.subject_id or concept.subject_id,
            "concept_id": concept.concept_id,
            "knowledge_point": concept.concept_id,
            "concept_name": concept.concept_name,
            "chapter_id": concept.chapter_id,
            "topic_id": concept.topic_id,
            "question_id": attempt.question_id,
            "selected_option": attempt.selected_option,
            "is_correct": bool(attempt.is_correct),
            "score": 1.0 if attempt.is_correct else 0.0,
            "confidence": 1.0,
            "source": "practice_attempt_backfill",
            "source_event_id": attempt.id,
            "created_at": attempt.created_at.isoformat() if attempt.created_at else "",
        }
        if dry_run:
            result["backfilled"] += 1
            continue
        repos.attempts.create_attempt(payload)
        graph.invoke(
            {
                "run_id": f"backfill-mastery:{attempt.id}",
                "user_id": attempt.user_id,
                "notebook_id": attempt.subject_id or concept.subject_id,
                "attempt_payloads": [payload],
            }
        )
        result["backfilled"] += 1
    return result


def _legacy_attempts(*, user_id: str | None, subject_id: str | None, limit: int) -> list[PracticeAttemptModel]:
    with session_scope() as session:
        stmt = select(PracticeAttemptModel).where(PracticeAttemptModel.concept_id != "")
        if user_id:
            stmt = stmt.where(PracticeAttemptModel.user_id == user_id)
        if subject_id:
            stmt = stmt.where(PracticeAttemptModel.subject_id == subject_id)
        stmt = stmt.order_by(PracticeAttemptModel.created_at.asc())
        if limit:
            stmt = stmt.limit(max(1, int(limit)))
        return list(session.scalars(stmt).all())


def _graph_attempt_exists(attempt_id: str) -> bool:
    with session_scope() as session:
        return session.get(GraphAttemptModel, attempt_id) is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="从旧 practice_attempts 回填 graph-era mastery_snapshots")
    parser.add_argument("--user-id", default=None, help="只回填指定用户")
    parser.add_argument("--subject-id", default=None, help="只回填指定学科")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条，0 表示不限")
    parser.add_argument("--dry-run", action="store_true", help="只统计可回填数据，不写入")
    args = parser.parse_args()

    load_dotenv()
    init_database()
    print(json.dumps(backfill(user_id=args.user_id, subject_id=args.subject_id, limit=args.limit, dry_run=args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
