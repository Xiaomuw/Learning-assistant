from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.config.validation import (  # noqa: E402
    EnvironmentValidationError,
    collect_environment_warnings,
    validate_startup_environment,
)
from app.infrastructure.auth.email_sender import (  # noqa: E402
    EmailSenderConfigurationError,
    send_register_verification_email,
)


class EnvironmentValidationTest(unittest.TestCase):
    def test_validate_startup_environment_accepts_postgres_and_strong_jwt(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
            },
            clear=True,
        ):
            validate_startup_environment()

    def test_validate_startup_environment_rejects_mysql(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "mysql+pymysql://user:pass@127.0.0.1:3306/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
            },
            clear=True,
        ):
            with self.assertRaises(EnvironmentValidationError) as ctx:
                validate_startup_environment()
        self.assertIn("PostgreSQL", str(ctx.exception))

    def test_validate_startup_environment_rejects_placeholder_jwt(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "replace-with-a-32-byte-or-longer-secret",
            },
            clear=True,
        ):
            with self.assertRaises(EnvironmentValidationError) as ctx:
                validate_startup_environment()
        self.assertIn("JWT_SECRET_KEY", str(ctx.exception))

    def test_collect_environment_warnings_reports_optional_capabilities(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
                "LANGSMITH_TRACING": "true",
                "MCP_ENABLED": "true",
            },
            clear=True,
        ):
            warnings = collect_environment_warnings()

        self.assertTrue(any("MODEL_ACCESS_KEY" in item for item in warnings))
        self.assertTrue(any("SMTP" in item for item in warnings))
        self.assertTrue(any("LANGSMITH_API_KEY" in item for item in warnings))
        self.assertTrue(any("MCP_WEB_SERVER_URL" in item for item in warnings))

    def test_collect_environment_warnings_reports_shared_do_embedding_endpoint(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
                "MODEL_ACCESS_KEY": "model-token",
                "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
                "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
            },
            clear=True,
        ):
            warnings = collect_environment_warnings()

        self.assertTrue(any("OPENAI_EMBEDDING_BASE_URL" in item for item in warnings))


class EmailSenderConfigurationTest(unittest.TestCase):
    def test_register_email_rejects_placeholder_smtp_before_connecting(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "587",
                "SMTP_USERNAME": "your-smtp-username",
                "SMTP_PASSWORD": "your-smtp-password",
                "SMTP_FROM_EMAIL": "no-reply@example.com",
            },
            clear=True,
        ), patch("app.infrastructure.auth.email_sender.smtplib.SMTP") as mocked_smtp:
            with self.assertRaises(EmailSenderConfigurationError) as ctx:
                send_register_verification_email("user@example.com", "123456")

        self.assertIn("SMTP 配置仍是占位值", str(ctx.exception))
        mocked_smtp.assert_not_called()

    def test_register_email_rejects_invalid_smtp_port_before_connecting(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SMTP_HOST": "smtp.gmail.com",
                "SMTP_PORT": "invalid",
                "SMTP_USERNAME": "xiaomuflz@gmail.com",
                "SMTP_PASSWORD": "app-password",
                "SMTP_FROM_EMAIL": "xiaomuflz@gmail.com",
            },
            clear=True,
        ), patch("app.infrastructure.auth.email_sender.smtplib.SMTP") as mocked_smtp:
            with self.assertRaises(EmailSenderConfigurationError) as ctx:
                send_register_verification_email("user@example.com", "123456")

        self.assertIn("SMTP_PORT", str(ctx.exception))
        mocked_smtp.assert_not_called()

    def test_register_email_uses_starttls_and_deliverability_headers(self) -> None:
        server = MagicMock()
        with patch.dict(
            os.environ,
            {
                "SMTP_HOST": "smtp.qq.com",
                "SMTP_PORT": "587",
                "SMTP_USERNAME": "sender@learning.test",
                "SMTP_PASSWORD": "app-password",
                "SMTP_FROM_EMAIL": "sender@learning.test",
                "SMTP_FROM_NAME": "Learning Assistant",
                "SMTP_USE_TLS": "true",
            },
            clear=True,
        ), patch("app.infrastructure.auth.email_sender.smtplib.SMTP") as mocked_smtp:
            mocked_smtp.return_value.__enter__.return_value = server

            send_register_verification_email("user@receiver.test", "123456")

        server.starttls.assert_called_once()
        sent_message = server.send_message.call_args.args[0]
        self.assertEqual(sent_message["Reply-To"], "sender@learning.test")
        self.assertTrue(sent_message["Date"])
        self.assertTrue(sent_message["Message-ID"])
        self.assertIn("text/html", sent_message.as_string())

    def test_register_email_can_use_smtp_ssl_without_starttls(self) -> None:
        server = MagicMock()
        with patch.dict(
            os.environ,
            {
                "SMTP_HOST": "smtp.qq.com",
                "SMTP_PORT": "465",
                "SMTP_USERNAME": "sender@learning.test",
                "SMTP_PASSWORD": "app-password",
                "SMTP_FROM_EMAIL": "sender@learning.test",
                "SMTP_USE_SSL": "true",
                "SMTP_USE_TLS": "true",
            },
            clear=True,
        ), patch("app.infrastructure.auth.email_sender.smtplib.SMTP_SSL") as mocked_ssl, patch(
            "app.infrastructure.auth.email_sender.smtplib.SMTP"
        ) as mocked_smtp:
            mocked_ssl.return_value.__enter__.return_value = server

            send_register_verification_email("user@receiver.test", "123456")

        mocked_ssl.assert_called_once_with("smtp.qq.com", 465, timeout=20)
        mocked_smtp.assert_not_called()
        server.starttls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
