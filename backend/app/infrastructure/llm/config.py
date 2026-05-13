from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_CHAT_MODEL = "deepseek-v4-flash"
DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-2"
DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_FALLBACK_CHAT_MODEL = "deepseek-v4-flash"
DEFAULT_NVIDIA_GLM_MODEL = "z-ai/glm4.7"
DEFAULT_LLM_TIMEOUT_SECONDS = 20.0
DEFAULT_LLM_MAX_RETRIES = 0
DEFAULT_CHAT_SYNC_TIMEOUT_SECONDS = 15.0
DEFAULT_PRACTICE_GENERATION_TIMEOUT_SECONDS = 6.0
DEFAULT_PRACTICE_REPAIR_TIMEOUT_SECONDS = 4.0
MODEL_SWITCHING_STATUS_DEVELOPMENT = "development"
MODEL_SWITCHING_STATUS_AVAILABLE = "available"


@dataclass(frozen=True)
class ChatModelConnection:
    model_id: str
    api_key: str | None
    base_url: str
    provider: str


@dataclass(frozen=True)
class EmbeddingModelConnection:
    model_id: str
    api_key: str | None
    base_url: str
    provider: str


def get_llm_timeout_seconds() -> float:
    raw = os.getenv("LLM_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_LLM_TIMEOUT_SECONDS

    try:
        return max(5.0, float(raw))
    except ValueError:
        return DEFAULT_LLM_TIMEOUT_SECONDS


def get_llm_max_retries() -> int:
    raw = os.getenv("LLM_MAX_RETRIES")
    if not raw:
        return DEFAULT_LLM_MAX_RETRIES

    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_LLM_MAX_RETRIES


def get_chat_sync_timeout_seconds() -> float:
    raw = os.getenv("CHAT_SYNC_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_CHAT_SYNC_TIMEOUT_SECONDS

    try:
        return max(3.0, float(raw))
    except ValueError:
        return DEFAULT_CHAT_SYNC_TIMEOUT_SECONDS


def _get_float_env(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


def _get_bool_env(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_model_switching_enabled() -> bool:
    raw = os.getenv("MODEL_SWITCHING_ENABLED")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_locked_chat_model() -> str:
    return os.getenv("LOCKED_CHAT_MODEL", DEFAULT_CHAT_MODEL).strip() or DEFAULT_CHAT_MODEL


def get_fallback_chat_model() -> str:
    return (
        os.getenv("FALLBACK_CHAT_MODEL", DEFAULT_FALLBACK_CHAT_MODEL).strip()
        or DEFAULT_FALLBACK_CHAT_MODEL
    )


def get_practice_generation_model() -> str:
    return (
        os.getenv("PRACTICE_GENERATION_MODEL", get_fallback_chat_model()).strip()
        or get_fallback_chat_model()
    )


def get_practice_generation_timeout_seconds() -> float:
    return _get_float_env(
        "PRACTICE_GENERATION_TIMEOUT_SECONDS",
        DEFAULT_PRACTICE_GENERATION_TIMEOUT_SECONDS,
        minimum=1.0,
    )


def get_practice_repair_timeout_seconds() -> float:
    return _get_float_env(
        "PRACTICE_REPAIR_TIMEOUT_SECONDS",
        DEFAULT_PRACTICE_REPAIR_TIMEOUT_SECONDS,
        minimum=1.0,
    )


def is_practice_recommendation_live_ai_enabled() -> bool:
    return _get_bool_env("PRACTICE_RECOMMENDATION_LIVE_AI", default=False)


def get_model_switching_status() -> str:
    return (
        MODEL_SWITCHING_STATUS_AVAILABLE
        if is_model_switching_enabled()
        else MODEL_SWITCHING_STATUS_DEVELOPMENT
    )


def ensure_model_env_aliases() -> None:
    """在运行时对齐 MODEL_ACCESS_KEY / OPENAI_API_KEY。"""
    model_access_key = os.getenv("MODEL_ACCESS_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if model_access_key and not openai_api_key:
        os.environ["OPENAI_API_KEY"] = model_access_key
    elif openai_api_key and not model_access_key:
        os.environ["MODEL_ACCESS_KEY"] = openai_api_key


def get_model_access_key() -> str | None:
    ensure_model_env_aliases()
    return os.getenv("MODEL_ACCESS_KEY") or os.getenv("OPENAI_API_KEY")


def get_embedding_api_key() -> str | None:
    return os.getenv("OPENAI_EMBEDDING_API_KEY") or get_model_access_key()


def get_nvidia_api_key() -> str | None:
    return os.getenv("NVIDIA_API_KEY")


def get_deepseek_api_key() -> str | None:
    return os.getenv("DEEPSEEK_API_KEY") or get_model_access_key()


def get_openai_compatible_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL)


def get_embedding_provider() -> str:
    """返回当前配置的 Embedding provider: 'google' 或 'openai-compatible'。"""
    return (os.getenv("EMBEDDING_PROVIDER") or "google").strip().lower()


def get_google_api_keys() -> list[str]:
    """返回所有配置的 Google API Key 列表（支持 GOOGLE_API_KEYS 逗号分隔或旧的 GOOGLE_API_KEY）。"""
    raw = (os.getenv("GOOGLE_API_KEYS") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


def get_google_api_key() -> str | None:
    """返回第一个 Google API Key（兼容旧调用方）。"""
    keys = get_google_api_keys()
    return keys[0] if keys else None


def get_google_embedding_model() -> str:
    return (os.getenv("GOOGLE_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip()


def get_embedding_base_url() -> str:
    return os.getenv("OPENAI_EMBEDDING_BASE_URL") or get_openai_compatible_base_url()


def get_embedding_model() -> str:
    """返回当前 Embedding 模型名称（兼容旧调用方）。"""
    provider = get_embedding_provider()
    if provider == "google":
        return get_google_embedding_model()
    return (
        os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL).strip()
        or DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL
    )


def get_fallback_embedding_model() -> str | None:
    """返回兜底 Embedding 模型名称，若未配置则返回 None。"""
    raw = (os.getenv("OPENAI_EMBEDDING_FALLBACK_MODEL") or "").strip()
    return raw or None


def get_nvidia_base_url() -> str:
    return os.getenv("NVIDIA_BASE_URL", DEFAULT_NVIDIA_BASE_URL)


def get_nvidia_glm_model() -> str:
    return os.getenv("NVIDIA_GLM_MODEL", DEFAULT_NVIDIA_GLM_MODEL).strip() or DEFAULT_NVIDIA_GLM_MODEL


def is_nvidia_chat_model(model_id: str | None) -> bool:
    normalized = (model_id or "").strip().lower()
    return normalized == get_nvidia_glm_model().lower() or normalized.startswith("z-ai/glm")


def is_deepseek_chat_model(model_id: str | None) -> bool:
    return (model_id or "").strip().lower().startswith("deepseek-")


def get_chat_model_connection(model_id: str | None) -> ChatModelConnection:
    selected_model = (model_id or get_locked_chat_model()).strip() or get_locked_chat_model()
    if is_nvidia_chat_model(selected_model):
        return ChatModelConnection(
            model_id=selected_model,
            api_key=get_nvidia_api_key(),
            base_url=get_nvidia_base_url(),
            provider="NVIDIA",
        )

    if is_deepseek_chat_model(selected_model):
        return ChatModelConnection(
            model_id=selected_model,
            api_key=get_deepseek_api_key(),
            base_url=get_openai_compatible_base_url(),
            provider="DeepSeek",
        )

    return ChatModelConnection(
        model_id=selected_model,
        api_key=get_model_access_key(),
        base_url=get_openai_compatible_base_url(),
        provider=_detect_chat_provider(get_openai_compatible_base_url()),
    )


def _detect_chat_provider(base_url: str) -> str:
    url_lower = base_url.lower()
    if "api.deepseek.com" in url_lower:
        return "DeepSeek"
    if "inference.do-ai.run" in url_lower:
        return "DigitalOcean"
    if "dashscope" in url_lower:
        return "DashScope"
    return "OpenAI-compatible"


def _detect_embedding_provider(base_url: str) -> str:
    url_lower = base_url.lower()
    if "api.deepseek.com" in url_lower:
        return "DeepSeek"
    if "inference.do-ai.run" in url_lower:
        return "DigitalOcean"
    if "dashscope" in url_lower:
        return "DashScope"
    return "OpenAI-compatible"


def get_embedding_model_connection(model_id: str | None = None) -> EmbeddingModelConnection:
    """返回当前 Embedding 模型连接信息。Google provider 返回 provider='Google'。"""
    provider = get_embedding_provider()
    if provider == "google":
        return EmbeddingModelConnection(
            model_id=model_id or get_google_embedding_model(),
            api_key=get_google_api_key(),
            base_url="",  # Google SDK 不使用 base_url
            provider="Google",
        )
    base_url = get_embedding_base_url()
    return EmbeddingModelConnection(
        model_id=(model_id or get_embedding_model()).strip() or DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MODEL,
        api_key=get_embedding_api_key(),
        base_url=base_url,
        provider=_detect_embedding_provider(base_url),
    )


def get_fallback_embedding_model_connection() -> EmbeddingModelConnection | None:
    """返回兜底 Embedding 模型连接，若未配置则返回 None。"""
    fallback_model = get_fallback_embedding_model()
    if not fallback_model:
        return None
    provider = get_embedding_provider()
    if provider == "google":
        return None  # Google 模型暂不配置 fallback
    base_url = get_embedding_base_url()
    return EmbeddingModelConnection(
        model_id=fallback_model,
        api_key=get_embedding_api_key(),
        base_url=base_url,
        provider=_detect_embedding_provider(base_url),
    )


def get_known_model_api_keys() -> list[str]:
    return [
        key
        for key in {
            get_model_access_key(),
            get_embedding_api_key(),
            get_deepseek_api_key(),
            get_nvidia_api_key(),
        }
        if key
    ]


def is_digitalocean_inference_endpoint() -> bool:
    return "inference.do-ai.run" in get_openai_compatible_base_url().lower()


def is_digitalocean_embedding_endpoint() -> bool:
    return "inference.do-ai.run" in get_embedding_base_url().lower()


def is_deepseek_endpoint() -> bool:
    return "api.deepseek.com" in get_openai_compatible_base_url().lower()


def get_embedding_check_ctx_length() -> bool:
    raw = os.getenv("EMBEDDING_CHECK_CTX_LENGTH")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    # DigitalOcean / DashScope 的 OpenAI 兼容 embedding endpoint 只接受字符串，
    # 而 LangChain 的 context-length checker 会把文本 tokenize 成整数数组发送，
    # 导致 400 错误。对这些 provider 必须关闭该检查。
    embedding_url = get_embedding_base_url().lower()
    if "inference.do-ai.run" in embedding_url or "dashscope" in embedding_url:
        return False
    return True
