from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.llm.langsmith import (
    get_langsmith_client,
    get_langsmith_settings,
    reset_langsmith_client_cache,
    sanitize_for_langsmith,
)


class LangSmithIntegrationTest(unittest.TestCase):
    def tearDown(self) -> None:
        reset_langsmith_client_cache()

    def test_langsmith_settings_disabled_when_flag_is_false(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LANGSMITH_TRACING": "false",
                "LANGSMITH_API_KEY": "test-key",
                "LANGSMITH_PROJECT": "learning-assistant-dev",
            },
            clear=False,
        ):
            reset_langsmith_client_cache()
            settings = get_langsmith_settings()

        self.assertFalse(settings.enabled)
        self.assertTrue(settings.has_api_key)
        self.assertEqual(settings.project, "learning-assistant-dev")

    def test_langsmith_client_uses_cloud_configuration_when_enabled(self) -> None:
        fake_client = object()
        with (
            patch.dict(
                os.environ,
                {
                    "LANGSMITH_TRACING": "true",
                    "LANGSMITH_API_KEY": "test-key",
                    "LANGSMITH_PROJECT": "learning-assistant-dev",
                    "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com",
                },
                clear=False,
            ),
            patch("app.infrastructure.llm.langsmith.Client", return_value=fake_client) as mock_client,
        ):
            reset_langsmith_client_cache()
            settings = get_langsmith_settings()
            client = get_langsmith_client()

        self.assertTrue(settings.enabled)
        self.assertIs(client, fake_client)
        mock_client.assert_called_once()
        kwargs = mock_client.call_args.kwargs
        self.assertEqual(kwargs["api_key"], "test-key")
        self.assertEqual(kwargs["api_url"], "https://api.smith.langchain.com")
        self.assertTrue(callable(kwargs["hide_inputs"]))
        self.assertTrue(callable(kwargs["hide_outputs"]))
        self.assertTrue(callable(kwargs["hide_metadata"]))

    def test_sanitizer_redacts_secrets_and_summarizes_large_context(self) -> None:
        payload = {
            "api_key": "this-should-not-appear-in-traces",
            "database_url": "postgresql://user:password@example/db",
            "notebook_context": "HTTP " * 200,
            "raw_retrieved_docs": [
                {"content": "HTTP 是应用层协议。", "score": 0.9},
                {"content": "TCP 是传输层协议。", "score": 0.8},
                {"content": "更多内容", "score": 0.7},
            ],
            "email": "student@example.com",
        }

        sanitized = sanitize_for_langsmith(payload)

        self.assertEqual(sanitized["api_key"], "<redacted>")
        self.assertIn("<redacted>", sanitized["database_url"])
        self.assertIn("<redacted-email>", sanitized["email"])
        self.assertEqual(sanitized["raw_retrieved_docs"]["count"], 3)
        self.assertEqual(sanitized["notebook_context"]["char_count"], len(payload["notebook_context"]))
        self.assertLessEqual(len(sanitized["notebook_context"]["preview"]), 540)


if __name__ == "__main__":
    unittest.main()
