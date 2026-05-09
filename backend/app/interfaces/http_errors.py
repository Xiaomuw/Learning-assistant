from __future__ import annotations

from fastapi import HTTPException

from app.application.errors import ApplicationError


def to_http_exception(exc: ApplicationError) -> HTTPException:
    if exc.reason:
        return HTTPException(
            status_code=exc.status_code,
            detail={
                "message": exc.detail,
                "reason": exc.reason,
            },
        )
    return HTTPException(status_code=exc.status_code, detail=exc.detail)
