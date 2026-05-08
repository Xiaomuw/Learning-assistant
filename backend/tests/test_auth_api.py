from __future__ import annotations

import importlib
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.postgres_test_utils import TemporaryPostgresSchema


class AuthApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db_schema = TemporaryPostgresSchema()
        self.db_schema.__enter__()
        self.db_schema.configure_env()
        os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-32-byte-length"

        for module_name in [
            "app.application.auth.service",
            "app.application.auth.verification",
            "app.infrastructure.auth.security",
            "app.infrastructure.auth.email_sender",
            "app.interfaces.auth.router",
            "app.interfaces.auth.dependencies",
            "app.interfaces.auth.cookies",
            "app.infrastructure.db.repositories.auth",
            "app.infrastructure.db.repositories.bootstrap",
            "app.infrastructure.db.models",
            "app.infrastructure.db.database",
        ]:
            sys.modules.pop(module_name, None)

        importlib.import_module("app.infrastructure.db.database")
        importlib.import_module("app.infrastructure.db.models")
        self.auth_repos = importlib.import_module("app.infrastructure.db.repositories.auth")
        self.bootstrap_repos = importlib.import_module("app.infrastructure.db.repositories.bootstrap")
        self.security = importlib.import_module("app.infrastructure.auth.security")
        self.verification = importlib.import_module("app.application.auth.verification")
        importlib.import_module("app.infrastructure.db.database").ensure_postgres_extensions()
        self.bootstrap_repos.init_database()

        auth_module = importlib.import_module("app.interfaces.auth.router")

        app = FastAPI()
        app.include_router(auth_module.router, prefix="/api")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.db_schema.__exit__(None, None, None)

    def _send_code(self, email: str) -> tuple[object, str]:
        with patch("app.application.auth.service.send_register_verification_email") as mocked_sender:
            response = self.client.post(
                "/api/auth/register/send-code",
                json={"email": email},
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(mocked_sender.called)
            code = mocked_sender.call_args.kwargs["code"]
        return response, code

    def test_send_code_returns_503_for_email_sender_failures_without_challenge(self) -> None:
        email_sender = importlib.import_module("app.infrastructure.auth.email_sender")
        cases = [
            (
                "smtp-missing@example.com",
                email_sender.EmailSenderConfigurationError("SMTP 配置仍是占位值：SMTP_HOST"),
                "SMTP 配置仍是占位值",
            ),
            (
                "smtp-failed@example.com",
                email_sender.EmailSenderError("SMTP 发信失败，请稍后重试"),
                "SMTP 发信失败",
            ),
        ]

        for email, sender_error, expected_detail in cases:
            with self.subTest(email=email), patch(
                "app.application.auth.service.send_register_verification_email",
                side_effect=sender_error,
            ):
                response = self.client.post(
                    "/api/auth/register/send-code",
                    json={"email": email},
                )

            self.assertEqual(response.status_code, 503)
            self.assertIn(expected_detail, response.json()["detail"])
            challenge = self.auth_repos.get_active_email_verification_challenge_record(email)
            self.assertIsNone(challenge)

    def test_send_code_complete_register_and_auth_flow(self) -> None:
        send_response, code = self._send_code("auth-user@example.com")
        self.assertEqual(send_response.json()["resend_after_seconds"], 60)

        challenge = self.auth_repos.get_active_email_verification_challenge_record("auth-user@example.com")
        self.assertIsNotNone(challenge)
        self.assertNotEqual(challenge.code_hash, code)

        register_response = self.client.post(
            "/api/auth/register/complete",
            json={
                "email": "auth-user@example.com",
                "code": code,
                "password": "password123",
                "display_name": "鉴权用户",
            },
        )
        self.assertEqual(register_response.status_code, 201)
        self.assertIn("la_access_token", register_response.cookies)
        self.assertIn("la_refresh_token", register_response.cookies)
        self.assertEqual(register_response.json()["user"]["display_name"], "鉴权用户")

        consumed_challenge = self.auth_repos.get_active_email_verification_challenge_record("auth-user@example.com")
        self.assertIsNone(consumed_challenge)

        reuse_response = self.client.post(
            "/api/auth/register/complete",
            json={
                "email": "auth-user@example.com",
                "code": code,
                "password": "password123",
            },
        )
        self.assertEqual(reuse_response.status_code, 409)

        me_response = self.client.get("/api/auth/me")
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["user"]["email"], "auth-user@example.com")

        logout_response = self.client.post("/api/auth/logout")
        self.assertEqual(logout_response.status_code, 200)

        unauthorized_me = self.client.get("/api/auth/me")
        self.assertEqual(unauthorized_me.status_code, 401)

        login_response = self.client.post(
            "/api/auth/login",
            json={"email": "auth-user@example.com", "password": "password123"},
        )
        self.assertEqual(login_response.status_code, 200)

        refresh_response = self.client.post("/api/auth/refresh")
        self.assertEqual(refresh_response.status_code, 200)
        self.assertIn("la_access_token", refresh_response.cookies)
        self.assertIn("la_refresh_token", refresh_response.cookies)

        change_password_response = self.client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "password456",
            },
        )
        self.assertEqual(change_password_response.status_code, 200)
        self.assertEqual(
            change_password_response.json()["user"]["email"],
            "auth-user@example.com",
        )

        self.client.post("/api/auth/logout")

        old_password_login = self.client.post(
            "/api/auth/login",
            json={"email": "auth-user@example.com", "password": "password123"},
        )
        self.assertEqual(old_password_login.status_code, 401)

        new_password_login = self.client.post(
            "/api/auth/login",
            json={"email": "auth-user@example.com", "password": "password456"},
        )
        self.assertEqual(new_password_login.status_code, 200)

    def test_send_code_rejects_registered_email_and_cooldown(self) -> None:
        _, code = self._send_code("cooldown@example.com")
        complete_response = self.client.post(
            "/api/auth/register",
            json={
                "email": "cooldown@example.com",
                "code": code,
                "password": "password123",
            },
        )
        self.assertEqual(complete_response.status_code, 201)

        with patch("app.application.auth.service.send_register_verification_email") as mocked_sender:
            duplicate_response = self.client.post(
                "/api/auth/register/send-code",
                json={"email": "cooldown@example.com"},
            )
            self.assertEqual(duplicate_response.status_code, 409)
            self.assertFalse(mocked_sender.called)

        with patch("app.application.auth.service.send_register_verification_email"):
            first_response = self.client.post(
                "/api/auth/register/send-code",
                json={"email": "fresh@example.com"},
            )
            self.assertEqual(first_response.status_code, 200)

            second_response = self.client.post(
                "/api/auth/register/send-code",
                json={"email": "fresh@example.com"},
            )
            self.assertEqual(second_response.status_code, 429)

    def test_wrong_code_expired_code_and_attempt_limit(self) -> None:
        _, code = self._send_code("attempts@example.com")

        wrong_response = self.client.post(
            "/api/auth/register/complete",
            json={
                "email": "attempts@example.com",
                "code": "999999",
                "password": "password123",
            },
        )
        self.assertEqual(wrong_response.status_code, 400)
        challenge = self.auth_repos.get_active_email_verification_challenge_record("attempts@example.com")
        self.assertEqual(challenge.attempt_count, 1)

        for _ in range(4):
            response = self.client.post(
                "/api/auth/register/complete",
                json={
                    "email": "attempts@example.com",
                    "code": "888888",
                    "password": "password123",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("次数已耗尽", response.json()["detail"])

        expired_expires_at = self.verification.utcnow() - timedelta(minutes=1)
        self.auth_repos.create_or_refresh_email_verification_challenge_record(
            email="expired@example.com",
            code_hash=self.security.hash_token("123456"),
            expires_at=expired_expires_at,
            purpose=self.verification.REGISTER_VERIFICATION_PURPOSE,
            max_attempts=self.verification.REGISTER_MAX_ATTEMPTS,
        )
        expired_response = self.client.post(
            "/api/auth/register/complete",
            json={
                "email": "expired@example.com",
                "code": "123456",
                "password": "password123",
            },
        )
        self.assertEqual(expired_response.status_code, 400)
        self.assertIn("已过期", expired_response.json()["detail"])

    def test_login_rejects_wrong_password(self) -> None:
        _, code = self._send_code("wrong-pass@example.com")
        register_response = self.client.post(
            "/api/auth/register/complete",
            json={
                "email": "wrong-pass@example.com",
                "code": code,
                "password": "password123",
            },
        )
        self.assertEqual(register_response.status_code, 201)

        response = self.client.post(
            "/api/auth/login",
            json={"email": "wrong-pass@example.com", "password": "bad-password"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
