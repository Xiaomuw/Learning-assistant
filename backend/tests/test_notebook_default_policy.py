from __future__ import annotations

import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-unit-tests")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.application.errors import ForbiddenError
from app.application.notebooks import service
from app.shared.schemas.contracts import SubjectRecord
from app.shared.schemas.subject import CANONICAL_SUBJECT_IDS, DEFAULT_SUBJECT_ID


def _subject(subject_id: str, name: str) -> SubjectRecord:
    return SubjectRecord(id=subject_id, name=name, icon="📚", description="")


class NotebookDefaultPolicyTest(unittest.TestCase):
    def test_regular_users_cannot_create_or_modify_default_notebooks(self) -> None:
        blocked_calls = [
            lambda: service.create_notebook("自定义知识库"),
            lambda: service.update_notebook("computer-network", "新名称"),
            lambda: service.delete_notebook("computer-network"),
            lambda: service.generate_notebook_knowledge_base("computer-network"),
        ]

        for call in blocked_calls:
            with self.subTest(call=call):
                with self.assertRaises(ForbiddenError):
                    call()

    def test_list_notebooks_only_returns_four_canonical_notebooks(self) -> None:
        records = [
            _subject("computer-network", "计算机网络"),
            _subject("data-structure", "数据结构与算法"),
            _subject("general", "通用知识"),
            _subject("database", "数据库原理"),
            _subject("computer-organization", "计算机组成原理"),
            _subject("operating-system", "操作系统原理"),
        ]

        with (
            patch("app.application.notebooks.service.list_subject_records", return_value=records),
            patch("app.application.notebooks.service.count_notebook_documents", return_value=0),
        ):
            notebooks = service.list_notebooks()

        self.assertEqual([item.id for item in notebooks], list(CANONICAL_SUBJECT_IDS))
        self.assertNotIn("general", [item.id for item in notebooks])
        self.assertNotIn("database", [item.id for item in notebooks])

    def test_legacy_general_notebook_request_normalizes_to_default(self) -> None:
        default_record = _subject(DEFAULT_SUBJECT_ID, "数据结构与算法")

        with (
            patch("app.application.notebooks.service.get_subject_record", return_value=default_record) as get_subject,
            patch("app.application.notebooks.service.count_notebook_documents", return_value=0),
        ):
            notebook = service.get_notebook("general")

        self.assertEqual(notebook.id, DEFAULT_SUBJECT_ID)
        get_subject.assert_called_once_with(DEFAULT_SUBJECT_ID)


if __name__ == "__main__":
    unittest.main()
