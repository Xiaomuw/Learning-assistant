"""
Import Taxonomy
===============
将 Concept Registry 的 YAML taxonomy 同步到 kb_subject/kb_chapter/kb_topic/kb_concept。

用法：
  python scripts/import_taxonomy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from sqlalchemy import func, select  # noqa: E402

from app.infrastructure.db.database import session_scope  # noqa: E402
from app.infrastructure.db.models import (
    KbChapterModel,
    KbConceptModel,
    KbSubjectModel,
    KbTopicModel,
)  # noqa: E402
from app.infrastructure.db.repositories.bootstrap import init_database  # noqa: E402
from app.infrastructure.db.repositories.knowledge_taxonomy import sync_knowledge_taxonomy  # noqa: E402


def main() -> None:
    init_database()
    synced = sync_knowledge_taxonomy()
    with session_scope() as session:
        subject_count = session.scalar(select(func.count()).select_from(KbSubjectModel)) or 0
        chapter_count = session.scalar(select(func.count()).select_from(KbChapterModel)) or 0
        topic_count = session.scalar(select(func.count()).select_from(KbTopicModel)) or 0
        concept_count = session.scalar(select(func.count()).select_from(KbConceptModel)) or 0

    print(
        "taxonomy 同步完成："
        f"subjects={subject_count}, "
        f"chapters={chapter_count}, "
        f"topics={topic_count}, "
        f"concepts={concept_count}, "
        f"synced_rows={synced}"
    )


if __name__ == "__main__":
    main()
