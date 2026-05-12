from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.config.validation import (  # noqa: E402
    EnvironmentValidationError,
    collect_environment_warnings,
    get_cors_allow_origins,
    validate_startup_environment,
)
from app.infrastructure.auth.email_sender import (  # noqa: E402
    EmailSenderConfigurationError,
    send_register_verification_email,
)
from scripts.check_environment import find_dotenv_shell_compatibility_issues  # noqa: E402


class EnvironmentValidationTest(unittest.TestCase):
    def test_dotenv_shell_check_flags_unquoted_whitespace_without_leaking_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        "LANGSMITH_API_KEY=secret-token-with-sensitive-value",
                        "LANGSMITH_PROJECT=Learning- Assistant 学习助理",
                    ]
                ),
                encoding="utf-8",
            )

            issues = find_dotenv_shell_compatibility_issues(dotenv_path)

        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue.line, 2)
        self.assertEqual(issue.key, "LANGSMITH_PROJECT")
        issue_text = str(issue)
        self.assertNotIn("Learning- Assistant", issue_text)
        self.assertNotIn("secret-token-with-sensitive-value", issue_text)

    def test_dotenv_shell_check_accepts_quoted_whitespace_and_inline_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        'LANGSMITH_PROJECT="Learning- Assistant 学习助理"',
                        'export SMTP_FROM_NAME="Learning Assistant"',
                        'QUOTED_WITH_COMMENT="Learning Assistant" # shell compatible',
                        "SIMPLE_VALUE=enabled # inline comments are shell compatible",
                    ]
                ),
                encoding="utf-8",
            )

            issues = find_dotenv_shell_compatibility_issues(dotenv_path)

        self.assertEqual(issues, [])

    def test_dotenv_shell_check_flags_unclosed_quote(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text('SMTP_FROM_NAME="Learning Assistant\n', encoding="utf-8")

            issues = find_dotenv_shell_compatibility_issues(dotenv_path)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].key, "SMTP_FROM_NAME")

    def test_validate_startup_environment_accepts_postgres_and_strong_jwt(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
                "APP_ENV": "development",
            },
            clear=True,
        ):
            validate_startup_environment()

    def test_validate_startup_environment_accepts_production_with_secure_cookie_and_origins(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "true",
                "CORS_ALLOW_ORIGINS": "https://learn.example.com,https://app.example.com",
                "WECHAT_MINI_APP_ID": "wxd338be42b166c393",
                "WECHAT_MINI_APP_SECRET": "wechat-mini-secret-for-production",
            },
            clear=True,
        ):
            validate_startup_environment()
            self.assertEqual(
                get_cors_allow_origins(),
                ["https://learn.example.com", "https://app.example.com"],
            )

    def test_validate_startup_environment_rejects_production_wildcard_cors(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "true",
                "CORS_ALLOW_ORIGINS": "*",
            },
            clear=True,
        ):
            with self.assertRaises(EnvironmentValidationError) as ctx:
                validate_startup_environment()
        self.assertIn("CORS_ALLOW_ORIGINS", str(ctx.exception))

    def test_validate_startup_environment_rejects_production_insecure_cookie(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "false",
                "CORS_ALLOW_ORIGINS": "https://learn.example.com",
            },
            clear=True,
        ):
            with self.assertRaises(EnvironmentValidationError) as ctx:
                validate_startup_environment()
        self.assertIn("AUTH_COOKIE_SECURE", str(ctx.exception))

    def test_validate_startup_environment_rejects_production_missing_wechat_mini_config(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/app",
                "JWT_SECRET_KEY": "learning-assistant-test-secret-2026",
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "true",
                "CORS_ALLOW_ORIGINS": "https://learn.example.com",
            },
            clear=True,
        ):
            with self.assertRaises(EnvironmentValidationError) as ctx:
                validate_startup_environment()
        self.assertIn("WECHAT_MINI_APP_ID", str(ctx.exception))

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
        self.assertTrue(any("微信小程序登录配置未完成" in item for item in warnings))
        self.assertTrue(any("LANGSMITH_API_KEY" in item for item in warnings))
        self.assertTrue(any("MCP_WEB_SERVER_URL" in item for item in warnings))
        self.assertTrue(any("ENABLE_PRACTICE_FINALIZER_WORKER" in item for item in warnings))

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
