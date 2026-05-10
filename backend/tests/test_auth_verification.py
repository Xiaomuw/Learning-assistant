from __future__ import annotations

import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.application.auth import verification as verification_module
from app.infrastructure.auth.security import validate_password_policy
from app.shared.schemas.contracts import EmailVerificationChallengeRecord


class AuthVerificationTest(unittest.TestCase):
    def test_generate_numeric_code_has_fixed_length(self) -> None:
        code = verification_module.generate_numeric_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_password_policy_rejects_blank_common_and_repeated_passwords(self) -> None:
        for password in ("        ", "password123", "aaaaaaaa", "12345678"):
            with self.subTest(password=password):
                with self.assertRaises(ValueError):
                    validate_password_policy(password)

        validate_password_policy("Str0ngPass123!")

    def test_verification_code_hash_uses_secret_keyed_hmac(self) -> None:
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "secret-one-for-verification"}, clear=False):
            first = verification_module.hash_verification_code("123456")
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "secret-two-for-verification"}, clear=False):
            second = verification_module.hash_verification_code("123456")

        self.assertNotEqual(first, "123456")
        self.assertNotEqual(first, second)

    def test_issue_register_verification_code_respects_cooldown(self) -> None:
        with patch(
            "app.application.auth.verification.get_active_email_verification_challenge",
            return_value=EmailVerificationChallengeRecord(
                id="challenge-cooldown",
                email="cooldown@example.com",
                code_hash="hash",
                expires_at=verification_module.utcnow() + timedelta(minutes=10),
                last_sent_at=verification_module.utcnow(),
            ),
        ):
            with self.assertRaises(verification_module.VerificationCooldownError):
                verification_module.issue_register_verification_code("cooldown@example.com")

    def test_verify_register_code_increments_attempts_on_mismatch(self) -> None:
        challenge = EmailVerificationChallengeRecord(
            id="challenge-1",
            email="user@example.com",
            code_hash=verification_module.hash_verification_code("123456"),
            attempt_count=0,
            max_attempts=verification_module.REGISTER_MAX_ATTEMPTS,
            expires_at=verification_module.utcnow() + timedelta(minutes=10),
        )
        with (
            patch(
                "app.application.auth.verification.get_active_email_verification_challenge",
                return_value=challenge,
            ),
            patch(
                "app.application.auth.verification.increment_email_verification_attempt",
                return_value=EmailVerificationChallengeRecord.model_validate(
                    {
                        **challenge.model_dump(),
                        "attempt_count": 1,
                    }
                ),
            ) as mocked_increment,
        ):
            with self.assertRaises(verification_module.VerificationCodeMismatchError):
                verification_module.verify_register_code("user@example.com", "654321")

        mocked_increment.assert_called_once_with("challenge-1")

    def test_verify_register_code_returns_challenge_on_success(self) -> None:
        challenge = EmailVerificationChallengeRecord(
            id="challenge-2",
            email="user@example.com",
            code_hash=verification_module.hash_verification_code("123456"),
            attempt_count=0,
            max_attempts=verification_module.REGISTER_MAX_ATTEMPTS,
            expires_at=verification_module.utcnow() + timedelta(minutes=10),
        )
        with patch(
            "app.application.auth.verification.get_active_email_verification_challenge",
            return_value=challenge,
        ):
            result = verification_module.verify_register_code("user@example.com", "123456")

        self.assertEqual(result.id, "challenge-2")


if __name__ == "__main__":
    unittest.main()
