from __future__ import annotations

from fastapi import HTTPException

from app.application.errors import ApplicationError


def to_http_exception(exc: ApplicationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)
