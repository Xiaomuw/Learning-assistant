"""
Auth API
========
本地邮箱密码注册 / 登录 / 刷新 / 退出。
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field

from app.application.auth.service import (
    change_password as change_password_service,
    complete_registration as complete_registration_service,
    get_current_user_view,
    login_with_wechat_mini_code as login_with_wechat_mini_code_service,
    login_user as login_user_service,
    logout_user as logout_user_service,
    refresh_user_session as refresh_user_session_service,
    send_register_code as send_register_code_service,
)
from app.application.errors import ApplicationError
from app.interfaces.auth.cookies import (
    REFRESH_COOKIE_NAME,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.interfaces.auth.dependencies import AuthenticatedUser, require_current_user
from app.interfaces.client_ip import client_host_from_request
from app.interfaces.http_errors import to_http_exception
from app.shared.schemas.contracts import AuthSessionResult, AuthUserView

router = APIRouter()


class AuthUserResponse(BaseModel):
    id: str
    email: str
    display_name: str


class AuthEnvelope(BaseModel):
    user: AuthUserResponse


class AuthTokenEnvelope(AuthEnvelope):
    access_token: str
    refresh_token: str


class RegisterRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)


class SendRegisterCodeRequest(BaseModel):
    email: EmailStr


class SendRegisterCodeResponse(BaseModel):
    message: str
    expires_in_seconds: int
    resend_after_seconds: int


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class WechatMiniLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=120)


class WechatMiniRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class WechatMiniLogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=4096)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def _build_auth_envelope(user: AuthUserView) -> AuthEnvelope:
    return AuthEnvelope(
        user=AuthUserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
        )
    )


def _issue_session_response(response: Response, result: AuthSessionResult) -> AuthEnvelope:
    set_auth_cookies(response, result.access_token, result.refresh_token)
    return _build_auth_envelope(result.user)


def _build_token_envelope(result: AuthSessionResult) -> AuthTokenEnvelope:
    user = _build_auth_envelope(result.user).user
    return AuthTokenEnvelope(
        user=user,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
    )


@router.post("/auth/register/send-code", response_model=SendRegisterCodeResponse)
async def send_register_code(body: SendRegisterCodeRequest, request: Request):
    try:
        result = send_register_code_service(
            str(body.email),
            client_host=client_host_from_request(request),
        )
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return SendRegisterCodeResponse.model_validate(result.model_dump())


@router.post("/auth/register/complete", response_model=AuthEnvelope, status_code=201)
async def complete_register(body: RegisterRequest, response: Response):
    try:
        result = complete_registration_service(
            email=str(body.email),
            code=body.code,
            password=body.password,
            display_name=body.display_name,
        )
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return _issue_session_response(response, result)


@router.post("/auth/register", response_model=AuthEnvelope, status_code=201)
async def register(body: RegisterRequest, response: Response):
    try:
        result = complete_registration_service(
            email=str(body.email),
            code=body.code,
            password=body.password,
            display_name=body.display_name,
        )
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return _issue_session_response(response, result)


@router.post("/auth/login", response_model=AuthEnvelope)
async def login(body: LoginRequest, response: Response):
    try:
        result = login_user_service(email=str(body.email), password=body.password)
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return _issue_session_response(response, result)


@router.post("/auth/wechat-mini/login", response_model=AuthTokenEnvelope)
def wechat_mini_login(body: WechatMiniLoginRequest, request: Request):
    try:
        result = login_with_wechat_mini_code_service(
            code=body.code,
            display_name=body.display_name,
            client_host=client_host_from_request(request),
        )
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return _build_token_envelope(result)


@router.post("/auth/wechat-mini/refresh", response_model=AuthTokenEnvelope)
async def wechat_mini_refresh(body: WechatMiniRefreshRequest):
    try:
        result = refresh_user_session_service(body.refresh_token)
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return _build_token_envelope(result)


@router.post("/auth/wechat-mini/logout")
async def wechat_mini_logout(body: WechatMiniLogoutRequest):
    result = logout_user_service(body.refresh_token)
    return result.model_dump()


@router.post("/auth/refresh", response_model=AuthEnvelope)
async def refresh_session(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    try:
        result = refresh_user_session_service(refresh_token)
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return _issue_session_response(response, result)


@router.post("/auth/logout")
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    result = logout_user_service(refresh_token)
    clear_auth_cookies(response)
    return result.model_dump()


@router.post("/auth/change-password", response_model=AuthEnvelope)
async def change_password(
    body: ChangePasswordRequest,
    response: Response,
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    try:
        result = change_password_service(
            user_id=current_user.id,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except ApplicationError as exc:
        raise to_http_exception(exc) from exc
    return _issue_session_response(response, result)


@router.get("/auth/me", response_model=AuthEnvelope)
async def get_me(
    current_user: AuthenticatedUser = Depends(require_current_user),
):
    return _build_auth_envelope(get_current_user_view(current_user))
