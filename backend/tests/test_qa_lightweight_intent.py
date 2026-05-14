from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.qa.lightweight_intent import (
    build_arithmetic_practice_answer_schema,
    build_simple_arithmetic_answer,
    classify_lightweight_answer_intent,
)


class QALightweightIntentTest(unittest.TestCase):
    def test_simple_arithmetic_is_direct_answer(self) -> None:
        self.assertEqual(classify_lightweight_answer_intent("1+1等于几"), "simple_fact")
        self.assertEqual(build_simple_arithmetic_answer("1+1等于几"), "1 + 1 = 2。")

    def test_arithmetic_practice_generation_outputs_clean_equations(self) -> None:
        answer = build_arithmetic_practice_answer_schema("帮我出几道一百以内的加减法运算")

        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("25 + 13 = ?", answer.final_answer)
        self.assertIn("88 − 35 = ?", answer.final_answer)
        self.assertNotIn("1+1=2", answer.final_answer)
        self.assertNotIn("递归", answer.final_answer)
        self.assertNotIn("链表", answer.final_answer)


if __name__ == "__main__":
    unittest.main()
