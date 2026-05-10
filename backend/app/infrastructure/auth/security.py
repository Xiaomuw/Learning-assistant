from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError

ACCESS_TOKEN_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_MINUTES", "15"))
REFRESH_TOKEN_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_DAYS", "7"))
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"

_COMMON_WEAK_PASSWORDS = {
    "12345678",
    "123456789",
    "1234567890",
    "11111111",
    "00000000",
    "password",
    "password1",
    "password12",
    "password123",
    "qwerty123",
    "qwer1234",
    "admin123",
    "admin1234",
    "learningassistant",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_password(password: str) -> bytes:
    # bcrypt only handles 72 bytes safely; pre-hashing keeps long passwords stable.
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_normalize_password(password), bcrypt.gensalt()).decode("utf-8")


def validate_password_policy(password: str) -> None:
    raw_password = str(password or "")
    effective_password = raw_password.strip()
    if len(effective_password) < 8:
        raise ValueError("密码至少需要 8 位有效字符")
    if len(raw_password) > 128:
        raise ValueError("密码不能超过 128 个字符")

    normalized = "".join(effective_password.lower().split())
    if normalized in _COMMON_WEAK_PASSWORDS:
        raise ValueError("密码过于常见，请换一个更安全的密码")
    if len(set(normalized)) <= 1:
        raise ValueError("密码不能由同一个字符重复组成")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            _normalize_password(password),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode_token(payload: dict[str, Any], expires_delta: timedelta) -> str:
    now = utcnow()
    claims = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(claims, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_access_token(user_id: str, email: str) -> tuple[str, datetime]:
    expires_at = utcnow() + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    token = _encode_token(
        {
            "sub": user_id,
            "email": email,
            "type": "access",
        },
        timedelta(minutes=ACCESS_TOKEN_MINUTES),
    )
    return token, expires_at


def create_refresh_token(user_id: str, email: str) -> tuple[str, str, datetime]:
    jti = str(uuid.uuid4())
    expires_at = utcnow() + timedelta(days=REFRESH_TOKEN_DAYS)
    token = _encode_token(
        {
            "sub": user_id,
            "email": email,
            "type": "refresh",
            "jti": jti,
        },
        timedelta(days=REFRESH_TOKEN_DAYS),
    )
    return token, jti, expires_at


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except InvalidTokenError as exc:
        raise ValueError("无效或已过期的登录凭证") from exc

    if payload.get("type") != expected_type:
        raise ValueError("登录凭证类型不匹配")

    return payload
