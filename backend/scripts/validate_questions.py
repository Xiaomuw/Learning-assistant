"""
Validate Practice Questions
===========================
校验单选题 JSON 是否满足 practice_question 导入要求。

用法：
  python scripts/validate_questions.py /path/to/questions.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.infrastructure.db.repositories.bootstrap import init_database
from app.infrastructure.db.repositories.practice_questions import (
    load_practice_question_json,
    validate_practice_questions,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 practice_question 单选题 JSON")
    parser.add_argument("path", help="题库 JSON 文件路径")
    args = parser.parse_args()

    load_dotenv()
    init_database()

    file_path = Path(args.path)
    raw_items = load_practice_question_json(file_path)
    result = validate_practice_questions(raw_items, source_file=str(file_path.resolve()))
    if result.valid:
        print(f"校验通过：{len(result.questions)} 道题可导入。")
        return

    print(f"校验失败：发现 {len(result.issues)} 个问题。", file=sys.stderr)
    for issue in result.issues:
        print(
            f"- 第 {issue.index} 条"
            f" question_id={issue.question_id or '<empty>'}"
            f" field={issue.field}: {issue.message}",
            file=sys.stderr,
        )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
