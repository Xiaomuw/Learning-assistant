from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.infrastructure.llm.provider as provider
from app.infrastructure.llm.config import get_chat_model_connection, get_embedding_model_connection
from app.infrastructure.llm.profile import get_model_profile


def _fake_client(model_ids: list[str]):
    return SimpleNamespace(
        inference=SimpleNamespace(
            list_models=lambda: {
                "data": [{"id": model_id} for model_id in model_ids],
            }
        )
    )


class LLMProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        provider._MODEL_CANDIDATE_CACHE["expires_at"] = 0.0
        provider._MODEL_CANDIDATE_CACHE["models"] = []
        provider._MODEL_CACHE["expires_at"] = 0.0
        provider._MODEL_CACHE["models"] = []
        provider._MODEL_CACHE["last_successful_models"] = []
        provider._MODEL_ACCESS_CACHE.clear()

    def tearDown(self) -> None:
        provider._MODEL_CANDIDATE_CACHE["expires_at"] = 0.0
        provider._MODEL_CANDIDATE_CACHE["models"] = []
        provider._MODEL_CACHE["expires_at"] = 0.0
        provider._MODEL_CACHE["models"] = []
        provider._MODEL_CACHE["last_successful_models"] = []
        provider._MODEL_ACCESS_CACHE.clear()

    def test_list_selectable_chat_models_returns_product_configured_models(self) -> None:
        with patch.dict(
            "os.environ",
            {"FALLBACK_CHAT_MODEL": "anthropic-claude-3-haiku-20240306"},
            clear=False,
        ):
            models = provider.list_selectable_chat_models(force_refresh=True)

        self.assertEqual(
            [item["id"] for item in models],
            ["openai-gpt-4.1", "anthropic-claude-3-haiku-20240306"],
        )
        self.assertEqual(models[1]["label"], "Claude 3 Haiku")
        self.assertEqual(models[1]["provider"], "Anthropic")

    def test_chat_model_connection_routes_gpt41_to_digitalocean(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MODEL_ACCESS_KEY": "do-token",
                "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
            },
            clear=False,
        ):
            connection = get_chat_model_connection("openai-gpt-4.1")

        self.assertEqual(connection.api_key, "do-token")
        self.assertEqual(connection.base_url, "https://inference.do-ai.run/v1")
        self.assertEqual(connection.provider, "DigitalOcean")

    def test_chat_model_connection_routes_claude_fallback_to_digitalocean(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MODEL_ACCESS_KEY": "do-token",
                "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
            },
            clear=False,
        ):
            connection = get_chat_model_connection("anthropic-claude-3-haiku-20240306")

        self.assertEqual(connection.model_id, "anthropic-claude-3-haiku-20240306")
        self.assertEqual(connection.api_key, "do-token")
        self.assertEqual(connection.base_url, "https://inference.do-ai.run/v1")
        self.assertEqual(connection.provider, "DigitalOcean")

    def test_chat_model_connection_routes_glm47_to_nvidia(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "NVIDIA_API_KEY": "nvidia-token",
                "NVIDIA_BASE_URL": "https://integrate.api.nvidia.com/v1",
                "NVIDIA_GLM_MODEL": "z-ai/glm4.7",
            },
            clear=False,
        ):
            connection = get_chat_model_connection("z-ai/glm4.7")

        self.assertEqual(connection.api_key, "nvidia-token")
        self.assertEqual(connection.base_url, "https://integrate.api.nvidia.com/v1")
        self.assertEqual(connection.provider, "NVIDIA")

    def test_embedding_model_connection_can_use_dedicated_provider(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MODEL_ACCESS_KEY": "do-token",
                "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
                "OPENAI_EMBEDDING_BASE_URL": "https://api.openai.test/v1",
                "OPENAI_EMBEDDING_API_KEY": "embedding-token",
                "OPENAI_EMBEDDING_MODEL": "text-embedding-3-large",
            },
            clear=False,
        ):
            connection = get_embedding_model_connection()

        self.assertEqual(connection.model_id, "text-embedding-3-large")
        self.assertEqual(connection.api_key, "embedding-token")
        self.assertEqual(connection.base_url, "https://api.openai.test/v1")
        self.assertEqual(connection.provider, "OpenAI-compatible")

    def test_get_embeddings_uses_dedicated_embedding_connection(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "MODEL_ACCESS_KEY": "do-token",
                    "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
                    "OPENAI_EMBEDDING_BASE_URL": "https://api.openai.test/v1",
                    "OPENAI_EMBEDDING_API_KEY": "embedding-token",
                    "OPENAI_EMBEDDING_MODEL": "text-embedding-3-large",
                },
                clear=False,
            ),
            patch("app.infrastructure.llm.clients.OpenAIEmbeddings") as mocked_embeddings,
        ):
            provider.get_embeddings(default_model="text-embedding-3-small")

        self.assertEqual(mocked_embeddings.call_args.kwargs["model"], "text-embedding-3-large")
        self.assertEqual(mocked_embeddings.call_args.kwargs["api_key"], "embedding-token")
        self.assertEqual(mocked_embeddings.call_args.kwargs["base_url"], "https://api.openai.test/v1")

    def test_glm47_tool_and_structured_capabilities_are_opt_in(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "NVIDIA_ENABLE_TOOL_CALLING": "false",
                "NVIDIA_ENABLE_STRUCTURED_OUTPUT": "false",
            },
            clear=False,
        ):
            profile = get_model_profile("z-ai/glm4.7")

        self.assertFalse(profile.supports_tool_calling)
        self.assertFalse(profile.supports_structured_output)

        with patch.dict(
            "os.environ",
            {
                "NVIDIA_ENABLE_TOOL_CALLING": "true",
                "NVIDIA_ENABLE_STRUCTURED_OUTPUT": "true",
            },
            clear=False,
        ):
            enabled_profile = get_model_profile("z-ai/glm4.7")

        self.assertTrue(enabled_profile.supports_tool_calling)
        self.assertTrue(enabled_profile.supports_structured_output)

    def test_model_health_snapshot_separates_chat_and_embedding_failures(self) -> None:
        with (
            patch("app.infrastructure.llm.provider.validate_chat_model_access", return_value=(True, None)),
            patch(
                "app.infrastructure.llm.provider.validate_embedding_model_access",
                return_value=(False, "embedding unavailable"),
            ),
            patch.dict(
                "os.environ",
                {
                    "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
                    "OPENAI_EMBEDDING_BASE_URL": "",
                    "OPENAI_EMBEDDING_MODEL": "all-mini-lm-l6-v2",
                },
                clear=False,
            ),
        ):
            snapshot = provider.build_model_health_snapshot(chat_model="llama3.3-70b-instruct")

        self.assertTrue(snapshot["chat_model_ok"])
        self.assertFalse(snapshot["embedding_model_ok"])
        self.assertEqual(snapshot["embedding_model_error"], "embedding unavailable")
        self.assertEqual(snapshot["chat_model"], "llama3.3-70b-instruct")

    def test_digitalocean_embedding_disables_context_length_checker_by_default(self) -> None:
        with patch.dict(
            "os.environ",
                {
                    "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
                    "OPENAI_EMBEDDING_BASE_URL": "",
                },
                clear=False,
        ):
            self.assertFalse(provider._get_embedding_check_ctx_length())

    def test_embedding_context_length_checker_can_be_overridden(self) -> None:
        with patch.dict(
            "os.environ",
                {
                    "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
                    "OPENAI_EMBEDDING_BASE_URL": "",
                    "EMBEDDING_CHECK_CTX_LENGTH": "true",
                },
                clear=False,
        ):
            self.assertTrue(provider._get_embedding_check_ctx_length())


if __name__ == "__main__":
    unittest.main()
