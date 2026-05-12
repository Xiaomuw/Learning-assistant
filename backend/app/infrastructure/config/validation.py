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
    "placeholder",
    "no-reply@example.com",
)

_WECHAT_PLACEHOLDER_MARKERS = (
    "replace-with",
    "placeholder",
    "your-wechat",
    "your-mini",
    "your-app",
    "appsecret",
    "appid",
)

_TRUE_VALUES = {"1", "true", "yes", "on"}


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


def get_cors_allow_origins() -> list[str]:
    raw = (os.getenv("CORS_ALLOW_ORIGINS") or "*").strip()
    if not raw:
        return ["*"]
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["*"]


def _is_production() -> bool:
    return (os.getenv("APP_ENV") or "development").strip().lower() == "production"


def _auth_cookie_secure_enabled() -> bool:
    return (os.getenv("AUTH_COOKIE_SECURE") or "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _wechat_mini_configured() -> bool:
    app_id = (os.getenv("WECHAT_MINI_APP_ID") or "").strip()
    app_secret = (os.getenv("WECHAT_MINI_APP_SECRET") or "").strip()
    return not (
        _looks_like_placeholder(app_id, _WECHAT_PLACEHOLDER_MARKERS)
        or _looks_like_placeholder(app_secret, _WECHAT_PLACEHOLDER_MARKERS)
    )


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in _TRUE_VALUES


def validate_startup_environment() -> None:
    """Validate startup-blocking environment variables."""
    _get_database_url()
    _get_jwt_secret()
    if _is_production():
        if "*" in get_cors_allow_origins():
            raise EnvironmentValidationError(
                "APP_ENV=production 时 CORS_ALLOW_ORIGINS 不能使用 '*'，请配置明确的前端域名。"
            )
        if not _auth_cookie_secure_enabled():
            raise EnvironmentValidationError(
                "APP_ENV=production 时必须设置 AUTH_COOKIE_SECURE=true，确保认证 Cookie 只通过 HTTPS 发送。"
            )
        if not _wechat_mini_configured():
            raise EnvironmentValidationError(
                "APP_ENV=production 时必须配置真实 WECHAT_MINI_APP_ID / WECHAT_MINI_APP_SECRET，"
                "否则微信小程序登录不可用。"
            )


def collect_environment_warnings() -> list[str]:
    warnings: list[str] = []

    model_access_key = (os.getenv("MODEL_ACCESS_KEY") or "").strip()
    openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not model_access_key and not openai_api_key:
        warnings.append(
            "未配置 MODEL_ACCESS_KEY / OPENAI_API_KEY，主问答链路将无法调用模型。"
        )
    embedding_base_url = (os.getenv("OPENAI_EMBEDDING_BASE_URL") or "").strip()
    openai_base_url = (os.getenv("OPENAI_BASE_URL") or "").strip()
    embedding_provider = (os.getenv("EMBEDDING_PROVIDER") or "google").strip().lower()
    if not embedding_base_url and "inference.do-ai.run" in openai_base_url.lower():
        warnings.append(
            "当前 embedding 默认复用 chat endpoint；若该 OpenAI-compatible provider 不提供 embedding，"
            "请配置 OPENAI_EMBEDDING_BASE_URL / OPENAI_EMBEDDING_API_KEY / OPENAI_EMBEDDING_MODEL。"
        )
    if (
        embedding_provider == "openai-compatible"
        and not embedding_base_url
        and "api.deepseek.com" in openai_base_url.lower()
    ):
        warnings.append(
            "当前 embedding 会复用 DeepSeek chat endpoint；DeepSeek V4 不提供 embedding，"
            "请配置 OPENAI_EMBEDDING_BASE_URL / OPENAI_EMBEDDING_API_KEY / OPENAI_EMBEDDING_MODEL。"
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
    else:
        smtp_host = smtp_values["SMTP_HOST"].lower()
        if any(marker in smtp_host for marker in ("smtp.qq.com", "foxmail", "gmail.com")):
            warnings.append(
                "当前使用个人邮箱 SMTP 发信，Gmail 可能将验证码放入垃圾邮件；生产建议配置 SPF/DKIM/DMARC 或专用邮件服务。"
            )

    if not _is_production() and not _wechat_mini_configured():
        warnings.append(
            "微信小程序登录配置未完成，/api/auth/wechat-mini/login 会返回 missing_config；"
            "本地真实登录需配置 WECHAT_MINI_APP_ID / WECHAT_MINI_APP_SECRET。"
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

    if (
        (_env_truthy("ENABLE_GRAPH_FACTS", default=True) or _env_truthy("ENABLE_GRAPH_DUAL_WRITE"))
        and not _env_truthy("ENABLE_PRACTICE_FINALIZER_WORKER")
    ):
        warnings.append(
            "graph-era facts 已启用但 ENABLE_PRACTICE_FINALIZER_WORKER 未开启；"
            "practice durable finalizer job 只能依赖请求内 opportunistic 执行，生产建议设置为 true。"
        )

    return warnings
