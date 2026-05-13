from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from app.infrastructure.observability.request_context import reset_request_id, set_request_id


REQUEST_ID_HEADER = "X-Request-ID"
CLIENT_REQUEST_ID_HEADER = "X-Client-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def _sanitize_request_id(value: str | None) -> str | None:
    candidate = (value or "").strip()
    if not candidate or not _REQUEST_ID_PATTERN.fullmatch(candidate):
        return None
    return candidate


def resolve_request_id(request: Request) -> str:
    return (
        _sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
        or _sanitize_request_id(request.headers.get(CLIENT_REQUEST_ID_HEADER))
        or uuid.uuid4().hex
    )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = resolve_request_id(request)
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started_at = time.perf_counter()
        client_host = request.client.host if request.client else "-"
        path = request.url.path

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.exception(
                "❌ HTTP 请求异常: request_id={} method={} path={} elapsed_ms={} client_host={}",
                request_id,
                request.method,
                path,
                elapsed_ms,
                client_host,
            )
            raise
        finally:
            reset_request_id(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        status_code = response.status_code

        if path == "/health" and status_code < 400:
            return response

        log_message = (
            "HTTP 请求完成: request_id={} method={} path={} status_code={} "
            "elapsed_ms={} client_host={}"
        )
        log_args = (request_id, request.method, path, status_code, elapsed_ms, client_host)
        if status_code >= 500:
            logger.error(log_message, *log_args)
        elif status_code >= 400:
            logger.warning(log_message, *log_args)
        else:
            logger.info(log_message, *log_args)

        return response
