"""
Import Practice Questions
=========================
校验并导入绑定 concept_id 的单选题 JSON 到独立 practice_question 表。

用法：
  python scripts/import_questions.py /path/to/questions.json --on-conflict skip
  python scripts/import_questions.py /path/to/questions.json --on-conflict upsert
  python scripts/import_questions.py /path/to/questions.json --dry-run
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from app.infrastructure.db.repositories.bootstrap import init_database
from app.infrastructure.db.repositories.practice_questions import (
    import_practice_questions,
    load_practice_question_json,
    validate_practice_questions,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 practice_question 单选题 JSON")
    parser.add_argument("path", help="题库 JSON 文件路径")
    parser.add_argument(
        "--on-conflict",
        choices=["skip", "upsert"],
        default="skip",
        help="question_id 已存在时跳过或更新，默认 skip",
    )
    parser.add_argument("--dry-run", action="store_true", help="只校验，不写入数据库")
    args = parser.parse_args()

    load_dotenv()
    init_database()

    file_path = Path(args.path)
    source_file = str(file_path.resolve())
    raw_items = load_practice_question_json(file_path)
    validation = validate_practice_questions(raw_items, source_file=source_file)
    validation.raise_for_errors()

    if args.dry_run:
        print(f"dry-run 校验通过：{len(validation.questions)} 道题可导入。")
        return

    result = import_practice_questions(
        raw_items,
        on_conflict=args.on_conflict,
        source_file=source_file,
    )
    print(
        "导入完成："
        f"total={result.total}, "
        f"inserted={result.inserted}, "
        f"updated={result.updated}, "
        f"skipped={result.skipped}"
    )


if __name__ == "__main__":
    main()
