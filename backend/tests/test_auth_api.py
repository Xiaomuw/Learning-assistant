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
                "password": "Str0ngPass123!",
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
                "password": "Str0ngPass123!",
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
            json={"email": "auth-user@example.com", "password": "Str0ngPass123!"},
        )
        self.assertEqual(login_response.status_code, 200)

        refresh_response = self.client.post("/api/auth/refresh")
        self.assertEqual(refresh_response.status_code, 200)
        self.assertIn("la_access_token", refresh_response.cookies)
        self.assertIn("la_refresh_token", refresh_response.cookies)

        change_password_response = self.client.post(
            "/api/auth/change-password",
            json={
                "current_password": "Str0ngPass123!",
                "new_password": "Str0ngPass456!",
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
            json={"email": "auth-user@example.com", "password": "Str0ngPass123!"},
        )
        self.assertEqual(old_password_login.status_code, 401)

        new_password_login = self.client.post(
            "/api/auth/login",
            json={"email": "auth-user@example.com", "password": "Str0ngPass456!"},
        )
        self.assertEqual(new_password_login.status_code, 200)

    def test_send_code_hides_registered_email_and_keeps_cooldown(self) -> None:
        _, code = self._send_code("cooldown@example.com")
        complete_response = self.client.post(
            "/api/auth/register",
            json={
                "email": "cooldown@example.com",
                "code": code,
                "password": "Str0ngPass123!",
            },
        )
        self.assertEqual(complete_response.status_code, 201)

        with patch("app.application.auth.service.send_register_verification_email") as mocked_sender:
            duplicate_response = self.client.post(
                "/api/auth/register/send-code",
                json={"email": "cooldown@example.com"},
            )
            self.assertEqual(duplicate_response.status_code, 200)
            self.assertIn("如果该邮箱可以注册", duplicate_response.json()["message"])
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
                "password": "Str0ngPass123!",
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
                    "password": "Str0ngPass123!",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("次数已耗尽", response.json()["detail"])

        expired_expires_at = self.verification.utcnow() - timedelta(minutes=1)
        self.auth_repos.create_or_refresh_email_verification_challenge_record(
            email="expired@example.com",
            code_hash=self.verification.hash_verification_code("123456"),
            expires_at=expired_expires_at,
            purpose=self.verification.REGISTER_VERIFICATION_PURPOSE,
            max_attempts=self.verification.REGISTER_MAX_ATTEMPTS,
        )
        expired_response = self.client.post(
            "/api/auth/register/complete",
            json={
                "email": "expired@example.com",
                "code": "123456",
                "password": "Str0ngPass123!",
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
                "password": "Str0ngPass123!",
            },
        )
        self.assertEqual(register_response.status_code, 201)

        response = self.client.post(
            "/api/auth/login",
            json={"email": "wrong-pass@example.com", "password": "WrongPass123!"},
        )
        self.assertEqual(response.status_code, 401)

    def test_wechat_mini_login_bearer_auth_and_refresh(self) -> None:
        with patch(
            "app.application.auth.service._exchange_wechat_mini_code",
            return_value={"openid": "openid-001", "unionid": "unionid-001"},
        ) as mocked_exchange:
            login_response = self.client.post(
                "/api/auth/wechat-mini/login",
                json={"code": "wx-code-001", "display_name": "微信学习者"},
            )

        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(mocked_exchange.called)
        payload = login_response.json()
        self.assertEqual(payload["user"]["display_name"], "微信学习者")
        self.assertTrue(payload["access_token"])
        self.assertTrue(payload["refresh_token"])

        bearer_me = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        self.assertEqual(bearer_me.status_code, 200)
        self.assertEqual(bearer_me.json()["user"]["id"], payload["user"]["id"])

        refresh_response = self.client.post(
            "/api/auth/wechat-mini/refresh",
            json={"refresh_token": payload["refresh_token"]},
        )
        self.assertEqual(refresh_response.status_code, 200)
        refreshed_payload = refresh_response.json()
        self.assertEqual(refreshed_payload["user"]["id"], payload["user"]["id"])
        self.assertTrue(refreshed_payload["access_token"])
        self.assertTrue(refreshed_payload["refresh_token"])

        replay_response = self.client.post(
            "/api/auth/wechat-mini/refresh",
            json={"refresh_token": payload["refresh_token"]},
        )
        self.assertEqual(replay_response.status_code, 200)
        replay_payload = replay_response.json()
        self.assertEqual(replay_payload["user"]["id"], payload["user"]["id"])
        self.assertEqual(replay_payload["refresh_token"], refreshed_payload["refresh_token"])

        replay_exhausted_response = self.client.post(
            "/api/auth/wechat-mini/refresh",
            json={"refresh_token": payload["refresh_token"]},
        )
        self.assertEqual(replay_exhausted_response.status_code, 401)

        logout_response = self.client.post(
            "/api/auth/wechat-mini/logout",
            json={"refresh_token": refreshed_payload["refresh_token"]},
        )
        self.assertEqual(logout_response.status_code, 200)
        refresh_after_logout = self.client.post(
            "/api/auth/wechat-mini/refresh",
            json={"refresh_token": refreshed_payload["refresh_token"]},
        )
        self.assertEqual(refresh_after_logout.status_code, 401)

    def test_wechat_mini_login_reuses_existing_openid_identity(self) -> None:
        with patch(
            "app.application.auth.service._exchange_wechat_mini_code",
            return_value={"openid": "openid-repeat", "unionid": "unionid-repeat"},
        ):
            first_response = self.client.post(
                "/api/auth/wechat-mini/login",
                json={"code": "wx-code-first", "display_name": "首次微信用户"},
            )
            second_response = self.client.post(
                "/api/auth/wechat-mini/login",
                json={"code": "wx-code-second", "display_name": "不会覆盖名字"},
            )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            first_response.json()["user"]["id"],
            second_response.json()["user"]["id"],
        )
        self.assertEqual(second_response.json()["user"]["display_name"], "首次微信用户")

    def test_bearer_token_takes_precedence_over_cookie(self) -> None:
        _, code = self._send_code("cookie-user@example.com")
        register_response = self.client.post(
            "/api/auth/register/complete",
            json={
                "email": "cookie-user@example.com",
                "code": code,
                "password": "Str0ngPass123!",
            },
        )
        self.assertEqual(register_response.status_code, 201)

        invalid_bearer_response = self.client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        self.assertEqual(invalid_bearer_response.status_code, 401)

    def test_wechat_mini_login_missing_config_returns_stable_reason(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WECHAT_MINI_APP_ID": "",
                "WECHAT_MINI_APP_SECRET": "",
            },
        ):
            response = self.client.post(
                "/api/auth/wechat-mini/login",
                json={"code": "wx-code-no-config"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["reason"], "missing_config")

    def test_wechat_mini_login_maps_code2session_errors(self) -> None:
        service_module = importlib.import_module("app.application.auth.service")

        cases = [
            (40029, 401, "invalid_code"),
            (40163, 401, "code_used"),
            (45011, 429, "rate_limited"),
            (-1, 503, "wechat_unavailable"),
            (40226, 401, "risk_blocked"),
        ]

        for errcode, expected_status, expected_reason in cases:
            with self.subTest(errcode=errcode):
                with patch.object(
                    service_module,
                    "_exchange_wechat_mini_code",
                    side_effect=lambda _code, errcode=errcode: service_module._raise_wechat_code_error(
                        {"errcode": errcode, "errmsg": "mocked"}
                    ),
                ):
                    response = self.client.post(
                        "/api/auth/wechat-mini/login",
                        json={"code": f"wx-code-{errcode}"},
                    )

                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json()["detail"]["reason"], expected_reason)


if __name__ == "__main__":
    unittest.main()
