"""
Import Taxonomy
===============
将 Concept Registry 的 YAML taxonomy 同步到 kb_subject/kb_chapter/kb_topic/kb_concept。

用法：
  python scripts/import_taxonomy.py
"""

from __future__ import annotations

from dotenv import load_dotenv
from sqlalchemy import func, select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import (
    KbChapterModel,
    KbConceptModel,
    KbSubjectModel,
    KbTopicModel,
)
from app.infrastructure.db.repositories.bootstrap import init_database
from app.infrastructure.db.repositories.knowledge_taxonomy import sync_knowledge_taxonomy


def main() -> None:
    load_dotenv()
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
