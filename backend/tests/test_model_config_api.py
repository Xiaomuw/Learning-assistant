from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.interfaces.auth.dependencies import require_current_user
from app.interfaces.api.model_config import router as model_router
from app.application.errors import ServiceUnavailableError, ValidationError
from app.shared.schemas.contracts import AuthUserView, ModelConfigSnapshot, ModelOptionRecord


class ModelConfigApiTest(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(model_router, prefix="/api")
        app.dependency_overrides[require_current_user] = lambda: AuthUserView(
            id="default_user",
            email="default@example.com",
            display_name="测试用户",
            status="active",
        )
        self.client = TestClient(app)

    def test_get_model_config_returns_locked_model_when_switching_is_disabled(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MODEL_SWITCHING_ENABLED": "false",
                "LOCKED_CHAT_MODEL": "llama3.3-70b-instruct",
            },
            clear=False,
        ):
            response = self.client.get("/api/settings/model")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_model"], "llama3.3-70b-instruct")
        self.assertEqual(payload["locked_model"], "llama3.3-70b-instruct")
        self.assertFalse(payload["model_switching_enabled"])
        self.assertEqual(payload["model_switching_status"], "development")
        self.assertEqual([item["id"] for item in payload["available_models"]], ["llama3.3-70b-instruct"])
        self.assertNotIn("GPT-5", payload["available_models"][0]["label"])

    def test_model_config_displays_default_google_embedding_model(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MODEL_SWITCHING_ENABLED": "false",
                "LOCKED_CHAT_MODEL": "llama3.3-70b-instruct",
                "EMBEDDING_PROVIDER": "google",
                "GOOGLE_EMBEDDING_MODEL": "models/gemini-embedding-2",
            },
            clear=False,
        ):
            response = self.client.get("/api/settings/model")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["embedding_model"], "models/gemini-embedding-2")

    def test_model_config_displays_openai_compatible_embedding_model(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MODEL_SWITCHING_ENABLED": "false",
                "LOCKED_CHAT_MODEL": "llama3.3-70b-instruct",
                "EMBEDDING_PROVIDER": "openai-compatible",
                "OPENAI_EMBEDDING_MODEL": "text-embedding-3-large",
            },
            clear=False,
        ):
            response = self.client.get("/api/settings/model")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["embedding_model"], "text-embedding-3-large")

    def test_locked_model_config_rejects_non_locked_update(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MODEL_SWITCHING_ENABLED": "false",
                "LOCKED_CHAT_MODEL": "llama3.3-70b-instruct",
            },
            clear=False,
        ):
            response = self.client.put("/api/settings/model", json={"chat_model": "kimi-k2.5"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "模型选择功能待开发，当前仅支持 Llama 3.3-70b-instruct",
        )

    def test_locked_model_config_accepts_locked_model_update_as_idempotent(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "MODEL_SWITCHING_ENABLED": "false",
                    "LOCKED_CHAT_MODEL": "llama3.3-70b-instruct",
                },
                clear=False,
            ),
            patch("app.application.model_config.service.set_app_setting_record"),
        ):
            response = self.client.put("/api/settings/model", json={"chat_model": "llama3.3-70b-instruct"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_model"], "llama3.3-70b-instruct")

    def test_model_health_returns_locked_model_status(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"MODEL_SWITCHING_ENABLED": "false", "LOCKED_CHAT_MODEL": "llama3.3-70b-instruct"},
                clear=False,
            ),
            patch("app.interfaces.api.model_config.validate_chat_model_access", return_value=(True, None)),
        ):
            response = self.client.get("/api/settings/model/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["chat_model"], "llama3.3-70b-instruct")
        self.assertTrue(payload["chat_model_ok"])
        self.assertIsNone(payload["chat_model_error"])

    def test_model_health_redacts_access_key_from_errors(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "MODEL_SWITCHING_ENABLED": "false",
                    "LOCKED_CHAT_MODEL": "llama3.3-70b-instruct",
                    "MODEL_ACCESS_KEY": "secret-token-for-test",
                    "OPENAI_API_KEY": "secret-token-for-test",
                },
                clear=False,
            ),
            patch(
                "app.interfaces.api.model_config.validate_chat_model_access",
                return_value=(False, "bad token secret-token-for-test"),
            ),
        ):
            response = self.client.get("/api/settings/model/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["chat_model_error"], "bad token [redacted]")

    def test_model_health_can_validate_selected_glm47_and_redact_nvidia_key(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "MODEL_SWITCHING_ENABLED": "true",
                    "NVIDIA_API_KEY": "nvidia-token-for-test",
                    "FALLBACK_CHAT_MODEL": "anthropic-claude-3-haiku-20240306",
                },
                clear=False,
            ),
            patch(
                "app.interfaces.api.model_config.validate_chat_model_access",
                return_value=(False, "bad token nvidia-token-for-test"),
            ),
        ):
            response = self.client.get("/api/settings/model/health?chat_model=z-ai/glm4.7")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["chat_model"], "z-ai/glm4.7")
        self.assertFalse(payload["chat_model_ok"])
        self.assertEqual(payload["chat_model_error"], "bad token [redacted]")
        self.assertTrue(payload["model_switching_enabled"])

    def test_model_health_ignores_requested_model_when_switching_is_disabled(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "MODEL_SWITCHING_ENABLED": "false",
                    "LOCKED_CHAT_MODEL": "llama3.3-70b-instruct",
                    "FALLBACK_CHAT_MODEL": "anthropic-claude-3-haiku-20240306",
                },
                clear=False,
            ),
            patch("app.interfaces.api.model_config.validate_chat_model_access", return_value=(True, None)) as mock_validate,
        ):
            response = self.client.get("/api/settings/model/health?chat_model=z-ai/glm4.7")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["chat_model"], "llama3.3-70b-instruct")
        self.assertFalse(payload["model_switching_enabled"])
        self.assertEqual(mock_validate.call_args.args[0], "llama3.3-70b-instruct")

    def test_get_model_config_falls_back_when_current_model_is_not_available(self) -> None:
        with patch(
            "app.interfaces.api.model_config.build_model_config_response",
            return_value=ModelConfigSnapshot(
                current_model="openai-gpt-oss-20b",
                embedding_model="text-embedding-3-small",
                available_models=[
                    ModelOptionRecord(id="openai-gpt-oss-20b", label="GPT-OSS-20B", provider="OpenAI", family="GPT"),
                    ModelOptionRecord(id="kimi-k2.5", label="Kimi-K2.5", provider="Moonshot", family="Kimi"),
                ],
            ),
        ):
            response = self.client.get("/api/settings/model")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_model"], "openai-gpt-oss-20b")

    def test_update_model_config_rejects_models_that_fail_access_check(self) -> None:
        with patch(
            "app.interfaces.api.model_config.update_active_chat_model",
            side_effect=ValidationError("该模型当前账号不可用或响应不稳定：quota exceeded"),
        ):
            response = self.client.put("/api/settings/model", json={"chat_model": "openai-gpt-oss-20b"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("quota exceeded", response.json()["detail"])

    def test_get_model_config_returns_503_when_no_model_is_available(self) -> None:
        with patch(
            "app.interfaces.api.model_config.build_model_config_response",
            side_effect=ServiceUnavailableError("当前账号未获取到可用聊天模型"),
        ):
            response = self.client.get("/api/settings/model")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "当前账号未获取到可用聊天模型")

    def test_update_model_config_rejects_models_outside_verified_available_list(self) -> None:
        with patch(
            "app.interfaces.api.model_config.update_active_chat_model",
            side_effect=ValidationError("该模型当前不可选，系统只展示当前账号真实可用的聊天模型"),
        ):
            response = self.client.put("/api/settings/model", json={"chat_model": "kimi-k2.5"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "该模型当前不可选，系统只展示当前账号真实可用的聊天模型",
        )

    def test_update_model_config_returns_updated_config_when_model_is_verified(self) -> None:
        with patch(
            "app.interfaces.api.model_config.update_active_chat_model",
            return_value=ModelConfigSnapshot(
                current_model="kimi-k2.5",
                embedding_model="text-embedding-3-small",
                available_models=[
                    ModelOptionRecord(id="openai-gpt-oss-20b", label="GPT-OSS-20B", provider="OpenAI", family="GPT"),
                    ModelOptionRecord(id="kimi-k2.5", label="Kimi-K2.5", provider="Moonshot", family="Kimi"),
                ],
            ),
        ):
            response = self.client.put("/api/settings/model", json={"chat_model": "kimi-k2.5"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_model"], "kimi-k2.5")
        self.assertEqual(
            [item["id"] for item in payload["available_models"]],
            ["openai-gpt-oss-20b", "kimi-k2.5"],
        )

    def test_model_switching_lists_gpt41_and_claude_fallback(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "MODEL_SWITCHING_ENABLED": "true",
                    "OPENAI_MODEL": "openai-gpt-4.1",
                    "FALLBACK_CHAT_MODEL": "anthropic-claude-3-haiku-20240306",
                },
                clear=False,
            ),
            patch(
                "app.application.model_config.service.ensure_available_active_chat_model",
                return_value="openai-gpt-4.1",
            ),
        ):
            response = self.client.get("/api/settings/model")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["model_switching_enabled"])
        self.assertEqual(payload["model_switching_status"], "available")
        self.assertEqual([item["id"] for item in payload["available_models"]], ["openai-gpt-4.1", "anthropic-claude-3-haiku-20240306"])

    def test_update_model_config_accepts_glm47_when_verified(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "MODEL_SWITCHING_ENABLED": "true",
                    "FALLBACK_CHAT_MODEL": "anthropic-claude-3-haiku-20240306",
                },
                clear=False,
            ),
            patch("app.application.model_config.service.validate_chat_model_access", return_value=(True, None)),
            patch("app.application.model_config.service.set_app_setting_record"),
            patch(
                "app.application.model_config.service.ensure_available_active_chat_model",
                return_value="anthropic-claude-3-haiku-20240306",
            ),
        ):
            response = self.client.put("/api/settings/model", json={"chat_model": "anthropic-claude-3-haiku-20240306"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_model"], "anthropic-claude-3-haiku-20240306")
        self.assertEqual([item["id"] for item in payload["available_models"]], ["openai-gpt-4.1", "anthropic-claude-3-haiku-20240306"])


if __name__ == "__main__":
    unittest.main()
