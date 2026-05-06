from __future__ import annotations

import os


class EnvironmentValidationError(RuntimeError):
    """Raised when startup-blocking environment configuration is invalid."""


_JWT_PLACEHOLDER_MARKERS = (
    "replace-with",
    "change-me",
    "changeme",
    "example",
    "placeholder",
    "dev-secret-change-me",
)

_SMTP_PLACEHOLDER_MARKERS = (
    "example.com",
    "your-smtp-",
    "replace-with",
)


def _is_blank(value: str | None) -> bool:
    return not (value or "").strip()


def _looks_like_placeholder(value: str | None, markers: tuple[str, ...]) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return True
    return any(marker in normalized for marker in markers)


def _get_database_url() -> str:
    value = (os.getenv("DATABASE_URL") or "").strip()
    if not value:
        raise EnvironmentValidationError(
            "缺少 DATABASE_URL。当前运行时只支持 PostgreSQL，例如 "
            "'postgresql+psycopg://learning_user:password@127.0.0.1:5432/learning_assistant'。"
        )
    if not value.startswith(("postgresql+psycopg://", "postgresql://", "postgres://")):
        raise EnvironmentValidationError(
            "DATABASE_URL 必须是 PostgreSQL DSN。当前项目已经不再支持 MySQL / SQLite 作为正式运行时数据库。"
        )
    return value


def _get_jwt_secret() -> str:
    value = (os.getenv("JWT_SECRET_KEY") or "").strip()
    if _is_blank(value):
        raise EnvironmentValidationError(
            "缺少 JWT_SECRET_KEY。登录注册已经启用，后端启动前必须提供长度足够的随机密钥。"
        )
    if _looks_like_placeholder(value, _JWT_PLACEHOLDER_MARKERS) or len(value) < 32:
        raise EnvironmentValidationError(
            "JWT_SECRET_KEY 仍是占位值或长度过短。请在 backend/.env 中替换为长度至少 32 的真实随机密钥。"
        )
    return value


def validate_startup_environment() -> None:
    """Validate startup-blocking environment variables."""
    _get_database_url()
    _get_jwt_secret()


def collect_environment_warnings() -> list[str]:
    warnings: list[str] = []

    model_access_key = (os.getenv("MODEL_ACCESS_KEY") or "").strip()
    openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not model_access_key and not openai_api_key:
        warnings.append(
            "未配置 MODEL_ACCESS_KEY / OPENAI_API_KEY，主问答链路将无法调用模型。"
        )

    smtp_keys = (
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_EMAIL",
    )
    smtp_values = {key: (os.getenv(key) or "").strip() for key in smtp_keys}
    if any(
        _is_blank(value) or _looks_like_placeholder(value, _SMTP_PLACEHOLDER_MARKERS)
        for value in smtp_values.values()
    ):
        warnings.append(
            "SMTP 配置未完成，/api/auth/register/send-code 会返回“未配置 SMTP”。"
        )

    if (os.getenv("LANGSMITH_TRACING") or "").strip().lower() == "true" and _is_blank(
        os.getenv("LANGSMITH_API_KEY")
    ):
        warnings.append(
            "LANGSMITH_TRACING=true 但未配置 LANGSMITH_API_KEY，LangSmith tracing 会自动降级为关闭。"
        )

    if (os.getenv("MCP_ENABLED") or "").strip().lower() == "true" and _is_blank(
        os.getenv("MCP_WEB_SERVER_URL")
    ):
        warnings.append(
            "MCP_ENABLED=true 但未配置 MCP_WEB_SERVER_URL，外部 MCP 增强会自动降级为关闭。"
        )

    return warnings
