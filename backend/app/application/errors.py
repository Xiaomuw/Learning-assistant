from __future__ import annotations


class ApplicationError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(ApplicationError):
    status_code = 404


class ConflictError(ApplicationError):
    status_code = 409


class ValidationError(ApplicationError):
    status_code = 400


class ForbiddenError(ApplicationError):
    status_code = 403


class UnauthorizedError(ApplicationError):
    status_code = 401


class ServiceUnavailableError(ApplicationError):
    status_code = 503


class ProcessingError(ApplicationError):
    status_code = 500


class RateLimitError(ApplicationError):
    status_code = 429
