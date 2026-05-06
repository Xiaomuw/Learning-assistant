from __future__ import annotations

import os

from fastapi import Response

from app.infrastructure.auth.security import ACCESS_TOKEN_MINUTES, REFRESH_TOKEN_DAYS

ACCESS_COOKIE_NAME = "la_access_token"
REFRESH_COOKIE_NAME = "la_refresh_token"
COOKIE_PATH = "/"
COOKIE_SAMESITE = "lax"
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=AUTH_COOKIE_SECURE,
        path=COOKIE_PATH,
        max_age=ACCESS_TOKEN_MINUTES * 60,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=AUTH_COOKIE_SECURE,
        path=COOKIE_PATH,
        max_age=REFRESH_TOKEN_DAYS * 24 * 60 * 60,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=AUTH_COOKIE_SECURE,
        path=COOKIE_PATH,
    )
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=AUTH_COOKIE_SECURE,
        path=COOKIE_PATH,
    )

