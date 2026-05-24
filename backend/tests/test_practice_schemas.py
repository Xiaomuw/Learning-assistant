from __future__ import annotations

import os
import unittest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.domains.practice.schemas import GeneratedQuizListOutput  # noqa: E402
from app.infrastructure.llm.structured import validate_schema_output  # noqa: E402


def _quiz_item(question: str = "HTTP 默认端口是哪一个？") -> dict:
    return {
        "difficulty": "基础",
        "question": question,
        "options": [
            {"key": "A", "text": "21"},
            {"key": "B", "text": "53"},
            {"key": "C", "text": "80"},
            {"key": "D", "text": "443"},
        ],
        "correct_option": "C",
        "explanation": "HTTP 的默认端口是 80，HTTPS 的默认端口是 443。",
        "option_rationales": {
            "A": "21 常用于 FTP。",
            "B": "53 常用于 DNS。",
            "C": "80 是 HTTP 默认端口。",
            "D": "443 是 HTTPS 默认端口。",
        },
        "knowledge_point": "HTTP 默认端口",
    }


class PracticeSchemaTest(unittest.TestCase):
    def test_generated_quiz_list_accepts_standard_items_object(self) -> None:
        result = GeneratedQuizListOutput.model_validate({"items": [_quiz_item()]})

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].correct_option, "C")

    def test_generated_quiz_list_accepts_bare_item_array(self) -> None:
        result = GeneratedQuizListOutput.model_validate(
            [_quiz_item("HTTP 和 HTTPS 默认端口对应关系？")]
        )

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].knowledge_point, "HTTP 默认端口")

    def test_generated_quiz_list_accepts_single_item_object(self) -> None:
        result = GeneratedQuizListOutput.model_validate(_quiz_item("未写端口的 HTTP URL 连接哪里？"))

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].question, "未写端口的 HTTP URL 连接哪里？")

    def test_structured_helper_passes_bare_list_to_schema_validator(self) -> None:
        result = validate_schema_output([_quiz_item()], GeneratedQuizListOutput)

        self.assertEqual(len(result.items), 1)


if __name__ == "__main__":
    unittest.main()
