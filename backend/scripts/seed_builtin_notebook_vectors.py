"""
Seed Built-in Notebook Vectors
==============================
为内置学习 notebook 写入确定性的基础章节向量内容。

用法:
  python scripts/seed_builtin_notebook_vectors.py --dry-run
  python scripts/seed_builtin_notebook_vectors.py
  python scripts/seed_builtin_notebook_vectors.py --subjects computer-network,database --force
  python scripts/seed_builtin_notebook_vectors.py --curriculum 408,math --with-questions --force
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(dotenv_path=BACKEND_ROOT / ".env")

from app.application.notebooks.builtin_seed import (  # noqa: E402
    build_builtin_seed_payload,
    get_builtin_seed_chapters,
    list_builtin_seed_subject_ids,
)
from app.application.notebooks.curriculum_seed import (  # noqa: E402
    build_curriculum_question_items,
    build_curriculum_seed_payload,
    iter_curriculum_branches,
    list_curriculum_package_ids,
)
from app.infrastructure.db.repositories.bootstrap import init_database  # noqa: E402
from app.infrastructure.db.repositories.practice import upsert_question_bank_item_records  # noqa: E402
from app.infrastructure.db.repositories.subjects import list_subject_records  # noqa: E402
from app.infrastructure.llm.provider import ensure_model_env_aliases  # noqa: E402
from app.services.rag.indexing import index_question_bank_items  # noqa: E402
from app.services.notebook_knowledge_base import (  # noqa: E402
    get_notebook_knowledge_status,
    ingest_notebook_documents,
)


@dataclass(frozen=True)
class SeedRunResult:
    subject_id: str
    status: str
    chapters: int
    chunks: int = 0
    questions: int = 0
    reason: str = ""


def _parse_subjects(raw_subjects: str | None) -> list[str]:
    if not raw_subjects:
        return list_builtin_seed_subject_ids()
    return [
        item.strip()
        for item in raw_subjects.split(",")
        if item.strip()
    ]


def _parse_curriculum(raw_curriculum: str | None) -> list[str]:
    if raw_curriculum is None:
        return []
    if raw_curriculum.strip().lower() in {"all", "*"}:
        return list_curriculum_package_ids()
    return [
        item.strip().lower()
        for item in raw_curriculum.split(",")
        if item.strip()
    ]


def _existing_subject_ids() -> set[str]:
    return {item.id for item in list_subject_records()}


def _known_dry_run_subject_ids(curriculum_ids: list[str] | None) -> set[str]:
    subject_ids = set(list_builtin_seed_subject_ids())
    if curriculum_ids:
        subject_ids.update(branch["subject_id"] for branch in iter_curriculum_branches(curriculum_ids))
    return subject_ids


def run_seed(
    *,
    subject_ids: list[str] | None = None,
    curriculum_ids: list[str] | None = None,
    with_questions: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> list[SeedRunResult]:
    existing_ids = _known_dry_run_subject_ids(curriculum_ids) if dry_run else _existing_subject_ids()
    requested_ids = subject_ids or list_builtin_seed_subject_ids()
    unknown_ids = [
        subject_id
        for subject_id in requested_ids
        if subject_id not in existing_ids
    ]
    if unknown_ids:
        raise RuntimeError(f"以下 notebook 不存在: {', '.join(unknown_ids)}")

    results: list[SeedRunResult] = []
    for subject_id in requested_ids:
        chapters = get_builtin_seed_chapters(subject_id)
        if not chapters:
            results.append(
                SeedRunResult(
                    subject_id=subject_id,
                    status="skipped",
                    chapters=0,
                    reason="没有内置 seed 内容",
                )
            )
            continue

        if dry_run:
            results.append(
                SeedRunResult(
                    subject_id=subject_id,
                    status="dry-run",
                    chapters=len(chapters),
                    reason=f"将写入 {len(chapters)} 个基础章节",
                )
            )
            continue

        status = get_notebook_knowledge_status(subject_id)
        should_seed = force or status.coverage_level in {"empty", "sparse"}
        if not should_seed:
            results.append(
                SeedRunResult(
                    subject_id=subject_id,
                    status="skipped",
                    chapters=len(chapters),
                    reason=f"当前覆盖度为 {status.coverage_level}，未使用 --force",
                )
            )
            continue

        texts, metadatas = build_builtin_seed_payload(subject_id)
        chunks = ingest_notebook_documents(
            subject_id=subject_id,
            texts=texts,
            metadatas=metadatas,
        )
        results.append(
            SeedRunResult(
                subject_id=subject_id,
                status="seeded",
                chapters=len(chapters),
                chunks=chunks,
            )
        )
    if curriculum_ids:
        curriculum_payload = build_curriculum_seed_payload(
            curriculum_ids,
            subject_ids=set(subject_ids or []),
        )
        curriculum_subject_ids = sorted(curriculum_payload.keys())
        unknown_curriculum_ids = [
            subject_id
            for subject_id in curriculum_subject_ids
            if subject_id not in existing_ids
        ]
        if unknown_curriculum_ids:
            raise RuntimeError(f"以下 curriculum notebook 不存在: {', '.join(unknown_curriculum_ids)}")

        question_items = build_curriculum_question_items(
            curriculum_ids,
            subject_ids=set(subject_ids or []),
        ) if with_questions else []
        question_counts_by_subject: dict[str, int] = {}
        for item in question_items:
            subject_id = str(item.get("subject_id") or "general")
            question_counts_by_subject[subject_id] = question_counts_by_subject.get(subject_id, 0) + 1

        for subject_id in curriculum_subject_ids:
            texts, metadatas = curriculum_payload[subject_id]
            if dry_run:
                results.append(
                    SeedRunResult(
                        subject_id=subject_id,
                        status="dry-run-curriculum",
                        chapters=len(texts),
                        questions=question_counts_by_subject.get(subject_id, 0),
                        reason=f"将写入 {len(texts)} 条课程内容和 {question_counts_by_subject.get(subject_id, 0)} 道题",
                    )
                )
                continue
            chunks = ingest_notebook_documents(
                subject_id=subject_id,
                texts=texts,
                metadatas=metadatas,
            )
            results.append(
                SeedRunResult(
                    subject_id=subject_id,
                    status="seeded-curriculum",
                    chapters=len(texts),
                    chunks=chunks,
                    questions=question_counts_by_subject.get(subject_id, 0),
                )
            )

        if with_questions and question_items and not dry_run:
            saved = upsert_question_bank_item_records(question_items)
            indexed = index_question_bank_items(
                [
                    {
                        **item,
                        "question_id": item["id"],
                        "source_type": "question_bank",
                    }
                    for item in question_items
                ]
            )
            results.append(
                SeedRunResult(
                    subject_id="question-bank",
                    status="seeded-questions",
                    chapters=0,
                    chunks=indexed,
                    questions=saved,
                    reason=f"题库写入 {saved} 道，向量写入 {indexed} 块",
                )
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="为内置 notebook 写入基础章节向量内容。")
    parser.add_argument(
        "--subjects",
        default=None,
        help="逗号分隔的 notebook id，例如 computer-network,database。默认处理全部内置 notebook。",
    )
    parser.add_argument(
        "--curriculum",
        default=None,
        help="逗号分隔的 curriculum 包，例如 408,math；使用 all 处理全部课程包。",
    )
    parser.add_argument("--with-questions", action="store_true", help="同时写入原创常考题型单选题并同步向量化。")
    parser.add_argument("--force", action="store_true", help="即使当前知识库不是空/稀疏也强制刷新 seed 内容。")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的操作，不写入 PGVector。")
    args = parser.parse_args()

    ensure_model_env_aliases()
    if not args.dry_run:
        init_database()

    results = run_seed(
        subject_ids=_parse_subjects(args.subjects),
        curriculum_ids=_parse_curriculum(args.curriculum),
        with_questions=args.with_questions,
        force=args.force,
        dry_run=args.dry_run,
    )
    print("Builtin notebook vector seed report:")
    for result in results:
        details = f"{result.status}: chapters={result.chapters}, chunks={result.chunks}, questions={result.questions}"
        if result.reason:
            details = f"{details}, reason={result.reason}"
        print(f"- {result.subject_id}: {details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
