from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.domains.practice.importer import import_question_bank_file


class QuestionBankIndexingTest(unittest.TestCase):
    def test_import_indexes_question_bank_items(self) -> None:
        payload = [
            {
                "id": "q-http-1",
                "subject_id": "computer-network",
                "knowledge_point": "HTTP",
                "question": "HTTP 默认端口是？",
                "options": [
                    {"key": "A", "text": "20"},
                    {"key": "B", "text": "53"},
                    {"key": "C", "text": "80"},
                    {"key": "D", "text": "443"},
                ],
                "correct_option": "C",
                "explanation": "HTTP 默认端口是 80。",
                "option_rationales": {"C": "80 是 HTTP 默认端口。"},
                "difficulty": "基础",
            }
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            with (
                patch(
                    "app.domains.practice.importer.upsert_question_bank_item_records",
                    return_value=1,
                ) as mocked_upsert,
                patch("app.domains.practice.importer.index_question_bank_items") as mocked_index,
            ):
                saved = import_question_bank_file(handle.name)

        self.assertEqual(saved, 1)
        mocked_upsert.assert_called_once()
        mocked_index.assert_called_once()
        indexed_payload = mocked_index.call_args.args[0]
        self.assertEqual(indexed_payload[0]["question_id"], "q-http-1")
        self.assertEqual(indexed_payload[0]["source_type"], "question_bank")


if __name__ == "__main__":
    unittest.main()
