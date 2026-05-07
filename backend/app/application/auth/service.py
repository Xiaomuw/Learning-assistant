from __future__ import annotations

from app.application.errors import (
    ConflictError,
    ProcessingError,
    RateLimitError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from app.infrastructure.db.repositories.auth import (
    create_auth_user_record,
    get_user_auth_record_by_email,
    get_user_auth_record_by_id,
    get_user_auth_view_record,
    revoke_refresh_token_by_jti,
    revoke_refresh_tokens_for_user,
    save_refresh_token_record,
    touch_user_last_login,
    touch_refresh_token_last_used_record,
    update_user_password_hash,
)
from app.application.auth.verification import (
    REGISTER_CODE_TTL_SECONDS,
    REGISTER_RESEND_COOLDOWN_SECONDS,
    VerificationAttemptsExceededError,
    VerificationCodeExpiredError,
    VerificationCodeMismatchError,
    VerificationCooldownError,
    consume_register_verification,
    issue_register_verification_code,
    mark_register_verification_verified,
    persist_register_verification_code,
    verify_register_code,
)
from app.infrastructure.auth.email_sender import (
    EmailSenderConfigurationError,
    EmailSenderError,
    send_register_verification_email,
)
from app.infrastructure.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.shared.schemas.contracts import (
    AuthSessionResult,
    AuthUserView,
    MessageResult,
    VerificationDispatchResult,
)


def _normalize_email(email: str) -> str:
    return str(email).strip().lower()


def _issue_auth_session(user: AuthUserView) -> AuthSessionResult:
    access_token, _ = create_access_token(user.id, user.email)
    refresh_token, refresh_jti, refresh_expires_at = create_refresh_token(user.id, user.email)
    save_refresh_token_record(
        user_id=user.id,
        token_jti=refresh_jti,
        token_hash=hash_token(refresh_token),
        expires_at=refresh_expires_at,
    )
    touch_user_last_login(user.id)
    return AuthSessionResult(
        user=user,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def send_register_code(email: str) -> VerificationDispatchResult:
    normalized_email = _normalize_email(email)
    if get_user_auth_record_by_email(normalized_email):
        raise ConflictError("该邮箱已注册")

    try:
        pending = issue_register_verification_code(normalized_email)
        send_register_verification_email(
            email=normalized_email,
            code=str(pending["plain_code"]),
            expires_in_minutes=REGISTER_CODE_TTL_SECONDS // 60,
        )
        persist_register_verification_code(
            email=normalized_email,
            code_hash=str(pending["code_hash"]),
            expires_at=pending["expires_at"],
        )
    except VerificationCooldownError as exc:
        raise RateLimitError(str(exc)) from exc
    except EmailSenderConfigurationError as exc:
        raise ServiceUnavailableError(str(exc)) from exc
    except EmailSenderError as exc:
        raise ServiceUnavailableError(str(exc)) from exc

    return VerificationDispatchResult(
        message="验证码已发送，请检查邮箱",
        expires_in_seconds=REGISTER_CODE_TTL_SECONDS,
        resend_after_seconds=REGISTER_RESEND_COOLDOWN_SECONDS,
    )


def complete_registration(
    *,
    email: str,
    code: str,
    password: str,
    display_name: str | None = None,
) -> AuthSessionResult:
    normalized_email = _normalize_email(email)
    if get_user_auth_record_by_email(normalized_email):
        raise ConflictError("该邮箱已注册")

    try:
        challenge = verify_register_code(normalized_email, code)
    except VerificationCodeMismatchError as exc:
        raise ValidationError(str(exc)) from exc
    except VerificationCodeExpiredError as exc:
        raise ValidationError(str(exc)) from exc
    except VerificationAttemptsExceededError as exc:
        raise ValidationError(str(exc)) from exc

    challenge_id = challenge.id.strip()
    if not challenge_id:
        raise ValidationError("验证码状态异常，请重新发送")

    try:
        user = create_auth_user_record(
            email=normalized_email,
            password_hash=hash_password(password),
            display_name=(display_name or "").strip() or None,
        )
    except ValueError as exc:
        if "已注册" in str(exc):
            consume_register_verification(challenge_id)
            raise ConflictError("该邮箱已注册") from exc
        raise ProcessingError(str(exc)) from exc

    mark_register_verification_verified(challenge_id)
    consume_register_verification(challenge_id)
    return _issue_auth_session(user)


def login_user(*, email: str, password: str) -> AuthSessionResult:
    user_record = get_user_auth_record_by_email(_normalize_email(email))
    if not user_record or not verify_password(password, user_record.password_hash):
        raise UnauthorizedError("邮箱或密码错误")

    auth_view = get_user_auth_view_record(user_record.id)
    if not auth_view:
        raise UnauthorizedError("用户不存在或已停用")

    revoke_refresh_tokens_for_user(auth_view.id)
    return _issue_auth_session(auth_view)


def refresh_user_session(refresh_token: str | None) -> AuthSessionResult:
    if not refresh_token:
        raise UnauthorizedError("缺少刷新凭证")

    try:
        payload = decode_token(refresh_token, "refresh")
    except ValueError as exc:
        raise UnauthorizedError(str(exc)) from exc

    user_id = str(payload.get("sub", "") or "").strip()
    token_jti = str(payload.get("jti", "") or "").strip()
    if not user_id or not token_jti:
        raise UnauthorizedError("刷新凭证无效")

    token_row = touch_refresh_token_last_used_record(token_jti)
    if not token_row or token_row.token_hash != hash_token(refresh_token):
        raise UnauthorizedError("刷新凭证已失效")

    revoke_refresh_token_by_jti(token_jti)
    auth_view = get_user_auth_view_record(user_id)
    if not auth_view:
        raise UnauthorizedError("用户不存在或已停用")

    return _issue_auth_session(auth_view)


def logout_user(refresh_token: str | None) -> MessageResult:
    if refresh_token:
        try:
            payload = decode_token(refresh_token, "refresh")
            token_jti = str(payload.get("jti", "") or "").strip()
            if token_jti:
                revoke_refresh_token_by_jti(token_jti)
        except ValueError:
            pass
    return MessageResult(message="已退出登录")


def change_password(
    *,
    user_id: str,
    current_password: str,
    new_password: str,
) -> AuthSessionResult:
    user_record = get_user_auth_record_by_id(user_id)
    if not user_record or user_record.status != "active":
        raise UnauthorizedError("用户不存在或已停用")

    if not verify_password(current_password, user_record.password_hash):
        raise UnauthorizedError("当前密码不正确")

    if current_password == new_password:
        raise ValidationError("新密码不能与当前密码相同")

    updated = update_user_password_hash(user_id, hash_password(new_password))
    if not updated:
        raise ProcessingError("更新密码失败")

    revoke_refresh_tokens_for_user(user_id)
    auth_view = get_user_auth_view_record(user_id)
    if not auth_view:
        raise UnauthorizedError("用户不存在或已停用")

    return _issue_auth_session(auth_view)


def get_current_user_view(current_user: AuthUserView) -> AuthUserView:
    return current_user


def authenticate_access_token(access_token: str | None) -> AuthUserView:
    if not access_token:
        raise UnauthorizedError("请先登录")

    try:
        payload = decode_token(access_token, "access")
    except ValueError as exc:
        raise UnauthorizedError(str(exc)) from exc

    user_id = str(payload.get("sub", "") or "").strip()
    if not user_id:
        raise UnauthorizedError("登录凭证缺少用户信息")

    user = get_user_auth_view_record(user_id)
    if not user:
        raise UnauthorizedError("用户不存在或已停用")
    return user
