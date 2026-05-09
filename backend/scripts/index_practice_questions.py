"""
Index Practice Questions
========================
从独立 practice_question 表读取题目，并可选写入向量库。

用法：
  python scripts/index_practice_questions.py --subject-id data-structure
  python scripts/index_practice_questions.py --concept-id data-structure.binary-tree.traversal --limit 100
  python scripts/index_practice_questions.py --dry-run
"""

from __future__ import annotations

import argparse
from collections import Counter
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from sqlalchemy import select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import PracticeQuestionModel
from app.infrastructure.db.repositories.bootstrap import init_database
from app.infrastructure.db.repositories.practice_questions import serialize_practice_question
from app.services.rag.indexing import index_practice_questions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="索引 practice_question 到向量库")
    parser.add_argument("--subject-id", default="", help="只索引指定 subject_id")
    parser.add_argument("--concept-id", default="", help="只索引指定 concept_id")
    parser.add_argument("--limit", type=_non_negative_int, default=None, help="最多读取多少道题")
    parser.add_argument("--dry-run", action="store_true", help="只读取并统计，不写入向量库")
    args = parser.parse_args(argv)

    init_database()

    items = load_practice_questions(
        subject_id=args.subject_id,
        concept_id=args.concept_id,
        limit=args.limit,
    )
    subject_counts = Counter(str(item.get("subject_id") or "general") for item in items)
    summary = ", ".join(
        f"{subject_id}={count}"
        for subject_id, count in sorted(subject_counts.items())
    ) or "无"

    if args.dry_run:
        print(f"dry-run：读取 {len(items)} 道 practice_question，按 subject 统计：{summary}")
        return 0

    written = index_practice_questions(items)
    print(
        f"索引完成：读取 {len(items)} 道 practice_question，"
        f"写入 {written} 个向量分块，按 subject 统计：{summary}"
    )
    return 0


def load_practice_questions(
    *,
    subject_id: str = "",
    concept_id: str = "",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    stmt = select(PracticeQuestionModel).order_by(PracticeQuestionModel.question_id)
    if subject_id:
        stmt = stmt.where(PracticeQuestionModel.subject_id == subject_id)
    if concept_id:
        stmt = stmt.where(PracticeQuestionModel.concept_id == concept_id)
    if limit is not None:
        stmt = stmt.limit(limit)

    with session_scope() as session:
        rows = session.scalars(stmt).all()
        return [serialize_practice_question(row) for row in rows]


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--limit 必须是整数") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("--limit 不能为负数")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
