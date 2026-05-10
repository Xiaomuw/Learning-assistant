"""
Import Question Bank
====================
将 CSV / JSON / Excel 题库导入当前 PostgreSQL。

用法：
  python scripts/import_question_bank.py /path/to/questions.csv --subject database
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.domains.practice.service import import_question_bank_file  # noqa: E402
from app.infrastructure.db.repositories.bootstrap import init_database  # noqa: E402
from app.infrastructure.llm.provider import ensure_model_env_aliases  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="导入选择题题库到当前数据库")
    parser.add_argument("path", help="CSV / JSON / Excel 文件路径")
    parser.add_argument("--subject", dest="subject_id", default=None, help="默认 subject/notebook id")
    args = parser.parse_args()

    ensure_model_env_aliases()
    init_database()

    count = import_question_bank_file(args.path, default_subject_id=args.subject_id)
    print(f"已导入 {count} 道题到题库：{Path(args.path).resolve()}")


if __name__ == "__main__":
    main()
