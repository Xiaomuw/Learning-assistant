from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.infrastructure.db.database import session_scope
from app.infrastructure.db.models import (
    AuthRefreshTokenModel,
    EmailVerificationChallengeModel,
    UserMemoryModel,
    UserModel,
    UserProfileModel,
)
from app.infrastructure.db.repositories._shared import (
    as_utc_datetime,
    serialize_email_verification_challenge_record,
    serialize_refresh_token_record,
    serialize_user_record,
    utcnow,
)
from app.shared.schemas.contracts import (
    AuthUserCredentialsRecord,
    AuthUserView,
    EmailVerificationChallengeRecord,
    RefreshTokenRecord,
)


def get_user_auth_record_by_email(email: str) -> AuthUserCredentialsRecord | None:
    with session_scope() as session:
        row = session.scalar(select(UserModel).where(UserModel.email == email.lower()))
        if not row:
            return None
        return AuthUserCredentialsRecord(
            id=row.id,
            email=row.email,
            password_hash=row.password_hash,
            status=row.status,
            last_login_at=row.last_login_at.isoformat() if row.last_login_at else "",
        )


def get_user_auth_record_by_id(user_id: str) -> AuthUserCredentialsRecord | None:
    with session_scope() as session:
        row = session.get(UserModel, user_id)
        if not row:
            return None
        return AuthUserCredentialsRecord(
            id=row.id,
            email=row.email,
            password_hash=row.password_hash,
            status=row.status,
            last_login_at=row.last_login_at.isoformat() if row.last_login_at else "",
        )


def get_user_auth_view_record(user_id: str) -> AuthUserView | None:
    with session_scope() as session:
        user = session.get(UserModel, user_id)
        if not user or user.status != "active":
            return None
        profile = session.get(UserProfileModel, user_id)
        return serialize_user_record(user, profile)


def create_auth_user_record(
    *,
    email: str,
    password_hash: str,
    display_name: str | None = None,
 ) -> AuthUserView:
    user_id = str(uuid.uuid4())
    email = email.lower().strip()
    profile_name = (display_name or "").strip() or email.split("@", 1)[0]
    with session_scope() as session:
        duplicate = session.scalar(select(UserModel).where(UserModel.email == email))
        if duplicate:
            raise ValueError("该邮箱已注册")
        user = UserModel(
            id=user_id,
            email=email,
            password_hash=password_hash,
            status="active",
        )
        profile = UserProfileModel(
            user_id=user_id,
            display_name=profile_name[:120],
            agent_style_name="",
            agent_style_prompt="",
            onboarding_completed=False,
        )
        memory = UserMemoryModel(
            user_id=user_id,
            weak_points=[],
            error_count={},
            recent_topics=[],
            last_session="",
        )
        session.add(user)
        session.add(profile)
        session.add(memory)
        session.flush()
        record = serialize_user_record(user, profile)
        if not record:
            raise RuntimeError("创建用户后序列化失败")
        return record


def touch_user_last_login(user_id: str) -> None:
    with session_scope() as session:
        row = session.get(UserModel, user_id)
        if not row:
            return
        row.last_login_at = utcnow()
        row.updated_at = utcnow()


def update_user_password_hash(user_id: str, password_hash: str) -> bool:
    with session_scope() as session:
        row = session.get(UserModel, user_id)
        if not row:
            return False
        row.password_hash = password_hash
        row.updated_at = utcnow()
        session.flush()
        return True


def save_refresh_token_record(
    user_id: str,
    token_jti: str,
    token_hash: str,
    expires_at: datetime,
) -> RefreshTokenRecord:
    with session_scope() as session:
        row = AuthRefreshTokenModel(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_jti=token_jti,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked_at=None,
            last_used_at=None,
        )
        session.add(row)
        session.flush()
        record = serialize_refresh_token_record(row)
        if not record:
            raise RuntimeError("刷新 token 序列化失败")
        return record


def touch_refresh_token_last_used_record(token_jti: str) -> RefreshTokenRecord | None:
    with session_scope() as session:
        row = session.scalar(select(AuthRefreshTokenModel).where(AuthRefreshTokenModel.token_jti == token_jti))
        if not row:
            return None
        now = utcnow()
        expires_at = as_utc_datetime(row.expires_at)
        revoked_at = as_utc_datetime(row.revoked_at)
        if revoked_at is not None or (expires_at is not None and expires_at <= now):
            return None
        row.last_used_at = now
        session.flush()
        return serialize_refresh_token_record(row)


def revoke_refresh_token_by_jti(token_jti: str) -> bool:
    with session_scope() as session:
        row = session.scalar(select(AuthRefreshTokenModel).where(AuthRefreshTokenModel.token_jti == token_jti))
        if not row:
            return False
        row.revoked_at = utcnow()
        session.flush()
        return True


def revoke_refresh_tokens_for_user(user_id: str) -> None:
    with session_scope() as session:
        rows = session.scalars(
            select(AuthRefreshTokenModel).where(
                AuthRefreshTokenModel.user_id == user_id,
                AuthRefreshTokenModel.revoked_at.is_(None),
            )
        ).all()
        now = utcnow()
        for row in rows:
            row.revoked_at = now
        session.flush()


def get_active_email_verification_challenge_record(
    email: str,
    purpose: str = "register",
) -> EmailVerificationChallengeRecord | None:
    email = email.lower().strip()
    now = utcnow()
    with session_scope() as session:
        row = session.scalar(
            select(EmailVerificationChallengeModel)
            .where(
                EmailVerificationChallengeModel.email == email,
                EmailVerificationChallengeModel.purpose == purpose,
                EmailVerificationChallengeModel.verified_at.is_(None),
                EmailVerificationChallengeModel.consumed_at.is_(None),
            )
            .order_by(EmailVerificationChallengeModel.updated_at.desc())
        )
        if not row:
            return None
        expires_at = as_utc_datetime(row.expires_at)
        if expires_at is not None and expires_at <= now:
            return None
        return serialize_email_verification_challenge_record(row)


def create_or_refresh_email_verification_challenge_record(
    *,
    email: str,
    code_hash: str,
    expires_at: datetime,
    purpose: str = "register",
    max_attempts: int = 5,
) -> EmailVerificationChallengeRecord:
    email = email.lower().strip()
    now = utcnow()
    with session_scope() as session:
        row = session.scalar(
            select(EmailVerificationChallengeModel)
            .where(
                EmailVerificationChallengeModel.email == email,
                EmailVerificationChallengeModel.purpose == purpose,
                EmailVerificationChallengeModel.verified_at.is_(None),
                EmailVerificationChallengeModel.consumed_at.is_(None),
            )
            .order_by(EmailVerificationChallengeModel.updated_at.desc())
        )
        if row is None:
            row = EmailVerificationChallengeModel(
                id=str(uuid.uuid4()),
                email=email,
                purpose=purpose,
                code_hash=code_hash,
                expires_at=expires_at,
                attempt_count=0,
                max_attempts=max_attempts,
                verified_at=None,
                consumed_at=None,
                last_sent_at=now,
            )
            session.add(row)
        else:
            row.code_hash = code_hash
            row.expires_at = expires_at
            row.attempt_count = 0
            row.max_attempts = max_attempts
            row.verified_at = None
            row.consumed_at = None
            row.last_sent_at = now
            row.updated_at = now
        session.flush()
        record = serialize_email_verification_challenge_record(row)
        if not record:
            raise RuntimeError("验证码 challenge 序列化失败")
        return record


def increment_email_verification_attempt_record(challenge_id: str) -> EmailVerificationChallengeRecord | None:
    with session_scope() as session:
        row = session.get(EmailVerificationChallengeModel, challenge_id)
        if not row:
            return None
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.updated_at = utcnow()
        session.flush()
        return serialize_email_verification_challenge_record(row)


def mark_email_verification_verified_record(challenge_id: str) -> EmailVerificationChallengeRecord | None:
    with session_scope() as session:
        row = session.get(EmailVerificationChallengeModel, challenge_id)
        if not row:
            return None
        row.verified_at = utcnow()
        row.updated_at = utcnow()
        session.flush()
        return serialize_email_verification_challenge_record(row)


def consume_email_verification_challenge_record(challenge_id: str) -> EmailVerificationChallengeRecord | None:
    with session_scope() as session:
        row = session.get(EmailVerificationChallengeModel, challenge_id)
        if not row:
            return None
        row.consumed_at = utcnow()
        row.updated_at = utcnow()
        session.flush()
        return serialize_email_verification_challenge_record(row)
