from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from app.infrastructure.auth.security import hash_token
from app.infrastructure.db.repositories.auth import (
    consume_email_verification_challenge_record,
    create_or_refresh_email_verification_challenge_record,
    get_active_email_verification_challenge_record,
    increment_email_verification_attempt_record,
    mark_email_verification_verified_record,
)
from app.shared.schemas.contracts import EmailVerificationChallengeRecord

REGISTER_VERIFICATION_PURPOSE = "register"
REGISTER_CODE_TTL_SECONDS = 10 * 60
REGISTER_RESEND_COOLDOWN_SECONDS = 60
REGISTER_MAX_ATTEMPTS = 5


class VerificationError(Exception):
    status_code = 400


class VerificationCooldownError(VerificationError):
    status_code = 429

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("验证码发送过于频繁，请稍后再试")
        self.retry_after_seconds = retry_after_seconds


class VerificationCodeExpiredError(VerificationError):
    pass


class VerificationAttemptsExceededError(VerificationError):
    pass


class VerificationCodeMismatchError(VerificationError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_verification_code(code: str) -> str:
    return hash_token(code.strip())


def generate_numeric_code(length: int = 6) -> str:
    alphabet = "0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def get_active_email_verification_challenge(email: str, purpose: str) -> EmailVerificationChallengeRecord | None:
    return get_active_email_verification_challenge_record(email=email, purpose=purpose)


def increment_email_verification_attempt(challenge_id: str) -> EmailVerificationChallengeRecord | None:
    return increment_email_verification_attempt_record(challenge_id)


def issue_register_verification_code(email: str) -> dict[str, object]:
    challenge = get_active_email_verification_challenge(
        email=email,
        purpose=REGISTER_VERIFICATION_PURPOSE,
    )
    now = utcnow()
    if challenge:
        last_sent_at = challenge.last_sent_at
        if isinstance(last_sent_at, datetime):
            retry_after = REGISTER_RESEND_COOLDOWN_SECONDS - int(
                max(0, (now - last_sent_at).total_seconds())
            )
            if retry_after > 0:
                raise VerificationCooldownError(retry_after)

    code = generate_numeric_code()
    expires_at = now + timedelta(seconds=REGISTER_CODE_TTL_SECONDS)
    return {
        "email": email.lower().strip(),
        "plain_code": code,
        "code_hash": hash_verification_code(code),
        "expires_at": expires_at,
        "expires_in_seconds": REGISTER_CODE_TTL_SECONDS,
        "resend_after_seconds": REGISTER_RESEND_COOLDOWN_SECONDS,
    }


def persist_register_verification_code(
    *,
    email: str,
    code_hash: str,
    expires_at: datetime,
) -> EmailVerificationChallengeRecord:
    return create_or_refresh_email_verification_challenge_record(
        email=email,
        code_hash=code_hash,
        expires_at=expires_at,
        purpose=REGISTER_VERIFICATION_PURPOSE,
        max_attempts=REGISTER_MAX_ATTEMPTS,
    )


def verify_register_code(email: str, code: str) -> EmailVerificationChallengeRecord:
    challenge = get_active_email_verification_challenge(
        email=email,
        purpose=REGISTER_VERIFICATION_PURPOSE,
    )
    if not challenge:
        raise VerificationCodeExpiredError("验证码已过期，请重新发送")

    expires_at = challenge.expires_at
    if isinstance(expires_at, datetime) and expires_at <= utcnow():
        raise VerificationCodeExpiredError("验证码已过期，请重新发送")

    attempt_count = int(challenge.attempt_count or 0)
    max_attempts = int(challenge.max_attempts or REGISTER_MAX_ATTEMPTS)
    if attempt_count >= max_attempts:
        raise VerificationAttemptsExceededError("验证码尝试次数已耗尽，请重新发送")

    if challenge.code_hash != hash_verification_code(code):
        updated = increment_email_verification_attempt(challenge.id)
        next_attempt_count = int((updated or challenge).attempt_count or 0)
        if next_attempt_count >= max_attempts:
            raise VerificationAttemptsExceededError("验证码尝试次数已耗尽，请重新发送")
        raise VerificationCodeMismatchError("验证码错误，请检查后重试")

    return challenge


def mark_register_verification_verified(challenge_id: str) -> None:
    mark_email_verification_verified_record(challenge_id)


def consume_register_verification(challenge_id: str) -> None:
    consume_email_verification_challenge_record(challenge_id)

