from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status

from app.application.auth.service import authenticate_access_token
from app.application.errors import UnauthorizedError
from app.interfaces.auth.cookies import ACCESS_COOKIE_NAME
from app.shared.schemas.contracts import AuthUserView

AuthenticatedUser = AuthUserView


def require_current_user(
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
) -> AuthenticatedUser:
    try:
        return authenticate_access_token(access_token)
    except UnauthorizedError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def verify_user_access(user_id: str, current_user: AuthenticatedUser = Depends(require_current_user)) -> AuthenticatedUser:
    if user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不能访问其他用户的数据")
    return current_user
