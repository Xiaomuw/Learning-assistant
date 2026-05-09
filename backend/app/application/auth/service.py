from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from json import JSONDecodeError
from threading import Lock
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.application.errors import (
    ConflictError,
    ProcessingError,
    RateLimitError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from app.infrastructure.db.repositories.auth import (
    consume_refresh_token_record,
    create_auth_user_record,
    get_user_auth_record_by_email,
    get_user_auth_record_by_id,
    get_user_auth_view_record,
    get_or_create_wechat_mini_user_record,
    revoke_refresh_token_by_jti,
    revoke_refresh_tokens_for_user,
    save_refresh_token_record,
    touch_user_last_login,
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


_REFRESH_REPLAY_TTL_SECONDS = float(os.getenv("AUTH_REFRESH_REPLAY_TTL_SECONDS", "5"))
_REFRESH_REPLAY_MAX_USES = int(os.getenv("AUTH_REFRESH_REPLAY_MAX_USES", "1"))


@dataclass
class _RefreshReplayEntry:
    result: AuthSessionResult
    expires_at: float
    remaining_uses: int


_refresh_replay_cache: dict[str, _RefreshReplayEntry] = {}
_refresh_replay_lock = Lock()


def _refresh_replay_key(user_id: str, token_jti: str, token_hash: str) -> str:
    return f"{user_id}:{token_jti}:{token_hash}"


def _remember_refresh_replay(
    *,
    user_id: str,
    token_jti: str,
    token_hash: str,
    result: AuthSessionResult,
) -> None:
    if _REFRESH_REPLAY_TTL_SECONDS <= 0 or _REFRESH_REPLAY_MAX_USES <= 0:
        return
    now = time.monotonic()
    with _refresh_replay_lock:
        _refresh_replay_cache[_refresh_replay_key(user_id, token_jti, token_hash)] = _RefreshReplayEntry(
            result=result,
            expires_at=now + _REFRESH_REPLAY_TTL_SECONDS,
            remaining_uses=_REFRESH_REPLAY_MAX_USES,
        )


def _consume_refresh_replay(
    *,
    user_id: str,
    token_jti: str,
    token_hash: str,
) -> AuthSessionResult | None:
    now = time.monotonic()
    key = _refresh_replay_key(user_id, token_jti, token_hash)
    with _refresh_replay_lock:
        expired_keys = [
            cache_key
            for cache_key, entry in _refresh_replay_cache.items()
            if entry.expires_at <= now or entry.remaining_uses <= 0
        ]
        for cache_key in expired_keys:
            _refresh_replay_cache.pop(cache_key, None)

        entry = _refresh_replay_cache.get(key)
        if not entry or entry.expires_at <= now or entry.remaining_uses <= 0:
            _refresh_replay_cache.pop(key, None)
            return None
        entry.remaining_uses -= 1
        if entry.remaining_uses <= 0:
            _refresh_replay_cache.pop(key, None)
        return entry.result


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


def _exchange_wechat_mini_code(code: str) -> dict[str, Any]:
    app_id = os.getenv("WECHAT_MINI_APP_ID", "").strip()
    app_secret = os.getenv("WECHAT_MINI_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise ServiceUnavailableError(
            "微信小程序登录未配置 WECHAT_MINI_APP_ID / WECHAT_MINI_APP_SECRET",
            reason="missing_config",
        )

    query = urlencode(
        {
            "appid": app_id,
            "secret": app_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )
    url = f"https://api.weixin.qq.com/sns/jscode2session?{query}"
    try:
        with urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError, URLError, TimeoutError, OSError) as exc:  # pragma: no cover - real network path
        raise ServiceUnavailableError(
            "微信登录服务暂时不可用，请稍后重试",
            reason="wechat_unavailable",
        ) from exc

    if payload.get("errcode"):
        _raise_wechat_code_error(payload)
    return payload


def _raise_wechat_code_error(payload: dict[str, Any]) -> None:
    code = int(payload.get("errcode") or 0)
    if code == 45011:
        raise RateLimitError("微信登录请求过于频繁，请稍后重试", reason="rate_limited")
    if code == -1:
        raise ServiceUnavailableError("微信登录服务暂时不可用，请稍后重试", reason="wechat_unavailable")
    if code == 40226:
        raise UnauthorizedError("微信登录暂时不可用，请稍后重试", reason="risk_blocked")
    if code == 40163:
        raise UnauthorizedError("微信登录凭证已使用或已过期，请重新登录", reason="code_used")
    if code == 40029:
        raise UnauthorizedError("微信登录凭证无效，请重新登录", reason="invalid_code")
    raise UnauthorizedError("微信登录凭证无效，请重新登录", reason="invalid_code")


def login_with_wechat_mini_code(
    *,
    code: str,
    display_name: str | None = None,
) -> AuthSessionResult:
    normalized_code = code.strip()
    if not normalized_code:
        raise ValidationError("缺少微信登录凭证")

    payload = _exchange_wechat_mini_code(normalized_code)
    openid = str(payload.get("openid", "") or "").strip()
    unionid = str(payload.get("unionid", "") or "").strip()
    if not openid:
        raise UnauthorizedError("微信登录凭证无效：缺少 openid", reason="invalid_code")

    try:
        user = get_or_create_wechat_mini_user_record(
            openid=openid,
            unionid=unionid,
            password_hash=hash_password(str(uuid.uuid4())),
            display_name=display_name,
        )
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc

    revoke_refresh_tokens_for_user(user.id)
    return _issue_auth_session(user)


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

    token_hash = hash_token(refresh_token)
    token_row = consume_refresh_token_record(
        token_jti=token_jti,
        token_hash=token_hash,
    )
    if not token_row:
        replayed = _consume_refresh_replay(
            user_id=user_id,
            token_jti=token_jti,
            token_hash=token_hash,
        )
        if replayed:
            return replayed
        raise UnauthorizedError("刷新凭证已失效")

    auth_view = get_user_auth_view_record(user_id)
    if not auth_view:
        raise UnauthorizedError("用户不存在或已停用")

    result = _issue_auth_session(auth_view)
    _remember_refresh_replay(
        user_id=user_id,
        token_jti=token_jti,
        token_hash=token_hash,
        result=result,
    )
    return result


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
