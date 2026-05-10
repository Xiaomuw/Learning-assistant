from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, sentinel

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.domains.practice.generation import (
    _invoke_generation_chain,
    build_mixed_practice_items_with_status,
    build_recommended_practice_items,
)
from app.infrastructure.llm.config import (
    get_practice_generation_model,
    get_practice_generation_timeout_seconds,
    get_practice_repair_timeout_seconds,
    is_practice_recommendation_live_ai_enabled,
)


class PracticeGenerationLatencyTest(unittest.TestCase):
    def test_practice_generation_defaults_to_fast_model_and_short_timeouts(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FALLBACK_CHAT_MODEL": "deepseek-v4-flash",
                "PRACTICE_GENERATION_MODEL": "",
                "PRACTICE_GENERATION_TIMEOUT_SECONDS": "",
                "PRACTICE_REPAIR_TIMEOUT_SECONDS": "",
                "PRACTICE_RECOMMENDATION_LIVE_AI": "",
            },
            clear=False,
        ):
            self.assertEqual(get_practice_generation_model(), "deepseek-v4-flash")
            self.assertEqual(get_practice_generation_timeout_seconds(), 6.0)
            self.assertEqual(get_practice_repair_timeout_seconds(), 4.0)
            self.assertFalse(is_practice_recommendation_live_ai_enabled())

    def test_generation_chain_uses_practice_model_and_purpose_timeout(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "PRACTICE_GENERATION_MODEL": "deepseek-v4-flash",
                    "PRACTICE_GENERATION_TIMEOUT_SECONDS": "6",
                    "PRACTICE_REPAIR_TIMEOUT_SECONDS": "4",
                },
                clear=False,
            ),
            patch("app.domains.practice.generation.get_generation_llm", return_value=sentinel.llm) as mocked_llm,
            patch("app.domains.practice.generation.invoke_with_schema", return_value=sentinel.output),
        ):
            generated = _invoke_generation_chain({"count": 1}, purpose="generation")
            generation_call = mocked_llm.call_args.kwargs
            mocked_llm.reset_mock()
            repaired = _invoke_generation_chain({"count": 1}, purpose="repair")
            repair_call = mocked_llm.call_args.kwargs

        self.assertIs(generated, sentinel.output)
        self.assertIs(repaired, sentinel.output)
        self.assertEqual(generation_call["model_name"], "deepseek-v4-flash")
        self.assertEqual(generation_call["timeout_seconds"], 6.0)
        self.assertEqual(generation_call["max_retries"], 0)
        self.assertEqual(repair_call["model_name"], "deepseek-v4-flash")
        self.assertEqual(repair_call["timeout_seconds"], 4.0)
        self.assertEqual(repair_call["max_retries"], 0)

    def test_generation_status_records_model_timeout_and_fallback_when_ai_times_out(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "PRACTICE_GENERATION_MODEL": "deepseek-v4-flash",
                    "PRACTICE_GENERATION_TIMEOUT_SECONDS": "6",
                },
                clear=False,
            ),
            patch("app.domains.practice.generation._list_question_bank_items", return_value=[]),
            patch("app.domains.practice.generation._invoke_generation_chain", side_effect=TimeoutError("slow")),
        ):
            result = build_mixed_practice_items_with_status(
                subject_id="data-structure",
                subject_name="数据结构",
                topic="栈",
                difficulty="基础",
                count=2,
                original_question="出两道栈的题",
                user_style_name="",
                user_style_prompt="",
                short_term_context="",
                session_memory_context="",
                long_term_context="",
                knowledge_points=["栈"],
            )

        status = result.status
        self.assertEqual(len(result.items), 2)
        self.assertEqual(status["model_name"], "deepseek-v4-flash")
        self.assertEqual(status["model_timeout_seconds"], 6.0)
        self.assertTrue(status["ai_model_used"])
        self.assertTrue(status["ai_generation_failed"])
        self.assertEqual(status["fallback_count"], 2)

    def test_recommendations_do_not_call_live_ai_by_default(self) -> None:
        with (
            patch.dict(os.environ, {"PRACTICE_RECOMMENDATION_LIVE_AI": "false"}, clear=False),
            patch("app.domains.practice.generation._list_practice_recommendations", return_value=[]),
            patch("app.domains.practice.generation._get_user_memory", return_value={"weak_points": ["栈"], "error_count": {}}),
            patch("app.domains.practice.generation._list_question_bank_items", return_value=[]),
            patch(
                "app.domains.practice.generation._invoke_generation_chain",
                side_effect=AssertionError("recommendation should not call live model"),
            ),
        ):
            items = build_recommended_practice_items(
                user_id="codex-test-user",
                subject_id="data-structure",
                subject_name="数据结构",
                user_style_name="",
                user_style_prompt="",
                limit=2,
                model_name="deepseek-v4-flash",
            )

        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.question for item in items))


if __name__ == "__main__":
    unittest.main()
