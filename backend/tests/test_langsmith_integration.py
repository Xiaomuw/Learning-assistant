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
    get_langsmith_health_status,
    get_langsmith_client,
    get_langsmith_settings,
    reset_langsmith_client_cache,
    sanitize_for_langsmith,
    trace_run,
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

    def test_trace_run_disabled_does_not_create_client(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "LANGSMITH_TRACING": "false",
                    "LANGSMITH_API_KEY": "test-key",
                    "LANGSMITH_PROJECT": "learning-assistant-dev",
                },
                clear=False,
            ),
            patch("app.infrastructure.llm.langsmith.Client") as mock_client,
        ):
            reset_langsmith_client_cache()
            with trace_run(name="test.disabled", inputs={"question": "什么是 HTTP？"}) as run:
                run.end(outputs={"answer": "HTTP 是应用层协议。"})

        mock_client.assert_not_called()

    def test_langsmith_health_reports_disabled_without_dns_probe(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "LANGSMITH_TRACING": "false",
                    "LANGSMITH_API_KEY": "test-key",
                    "LANGSMITH_PROJECT": "learning-assistant-dev",
                },
                clear=False,
            ),
            patch("app.infrastructure.llm.langsmith.socket.getaddrinfo") as getaddrinfo,
        ):
            reset_langsmith_client_cache()
            status = get_langsmith_health_status()

        self.assertEqual(status["status"], "disabled")
        getaddrinfo.assert_not_called()

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

    def test_langsmith_runtime_aliases_align_langchain_project(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "test-key",
                "LANGSMITH_PROJECT": "Learning- Assistant 学习助理",
                "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com",
            },
            clear=False,
        ):
            reset_langsmith_client_cache()
            settings = get_langsmith_settings()
            status = get_langsmith_health_status()
            langchain_tracing = os.environ["LANGCHAIN_TRACING_V2"]
            langchain_project = os.environ["LANGCHAIN_PROJECT"]
            langchain_endpoint = os.environ["LANGCHAIN_ENDPOINT"]
            langchain_api_key = os.environ["LANGCHAIN_API_KEY"]

        self.assertEqual(settings.project, "Learning- Assistant 学习助理")
        self.assertEqual(langchain_tracing, "true")
        self.assertEqual(langchain_project, "Learning- Assistant 学习助理")
        self.assertEqual(langchain_endpoint, "https://api.smith.langchain.com")
        self.assertEqual(langchain_api_key, "test-key")
        self.assertEqual(status["project"], "Learning- Assistant 学习助理")
        self.assertTrue(status["has_api_key"])
        self.assertNotIn("test-key", str(status))

    def test_sanitizer_redacts_secrets_and_summarizes_large_context(self) -> None:
        long_question = "什么是 HTTP？" * 200
        long_answer = "HTTP 是应用层协议。" * 200
        payload = {
            "api_key": "this-should-not-appear-in-traces",
            "database_url": "postgresql://user:password@example/db",
            "question": long_question,
            "answer": long_answer,
            "notebook_context": "HTTP " * 200,
            "raw_retrieved_docs": [
                {"content": "HTTP 是应用层协议。", "score": 0.9},
                {"content": "TCP 是传输层协议。", "score": 0.8},
                {"content": "更多内容", "score": 0.7},
            ],
            "reasoning_content": "hidden chain of thought",
            "message_blocks": [
                {"type": "reasoning_content", "text": "hidden model reasoning"},
                {"type": "text", "text": "visible answer"},
            ],
            "email": "student@example.com",
        }

        sanitized = sanitize_for_langsmith(payload)

        self.assertEqual(sanitized["api_key"], "<redacted>")
        self.assertIn("<redacted>", sanitized["database_url"])
        self.assertIn("<redacted-email>", sanitized["email"])
        self.assertEqual(sanitized["question"], long_question)
        self.assertEqual(sanitized["answer"], long_answer)
        self.assertEqual(sanitized["raw_retrieved_docs"]["count"], 3)
        self.assertEqual(sanitized["notebook_context"]["char_count"], len(payload["notebook_context"]))
        self.assertLessEqual(len(sanitized["notebook_context"]["preview"]), 540)
        self.assertTrue(sanitized["reasoning_content"]["redacted"])
        self.assertTrue(sanitized["message_blocks"][0]["redacted"])
        self.assertEqual(sanitized["message_blocks"][1]["text"], "visible answer")


if __name__ == "__main__":
    unittest.main()
