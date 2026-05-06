from __future__ import annotations

import os
from dataclasses import dataclass

from pydo import Client

DEFAULT_DO_BASE_URL = "https://inference.do-ai.run/v1"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_CHAT_MODEL = "openai-gpt-4.1"
DEFAULT_FALLBACK_CHAT_MODEL = "anthropic-claude-3-haiku-20240306"
DEFAULT_NVIDIA_GLM_MODEL = "z-ai/glm4.7"
DEFAULT_LLM_TIMEOUT_SECONDS = 45.0
DEFAULT_LLM_MAX_RETRIES = 1
MODEL_SWITCHING_STATUS_DEVELOPMENT = "development"
MODEL_SWITCHING_STATUS_AVAILABLE = "available"


@dataclass(frozen=True)
class ChatModelConnection:
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


def get_nvidia_api_key() -> str | None:
    return os.getenv("NVIDIA_API_KEY")


def get_openai_compatible_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", DEFAULT_DO_BASE_URL)


def get_nvidia_base_url() -> str:
    return os.getenv("NVIDIA_BASE_URL", DEFAULT_NVIDIA_BASE_URL)


def get_nvidia_glm_model() -> str:
    return os.getenv("NVIDIA_GLM_MODEL", DEFAULT_NVIDIA_GLM_MODEL).strip() or DEFAULT_NVIDIA_GLM_MODEL


def is_nvidia_chat_model(model_id: str | None) -> bool:
    normalized = (model_id or "").strip().lower()
    return normalized == get_nvidia_glm_model().lower() or normalized.startswith("z-ai/glm")


def get_chat_model_connection(model_id: str | None) -> ChatModelConnection:
    selected_model = (model_id or get_locked_chat_model()).strip() or get_locked_chat_model()
    if is_nvidia_chat_model(selected_model):
        return ChatModelConnection(
            model_id=selected_model,
            api_key=get_nvidia_api_key(),
            base_url=get_nvidia_base_url(),
            provider="NVIDIA",
        )

    return ChatModelConnection(
        model_id=selected_model,
        api_key=get_model_access_key(),
        base_url=get_openai_compatible_base_url(),
        provider="DigitalOcean",
    )


def get_known_model_api_keys() -> list[str]:
    return [key for key in {get_model_access_key(), get_nvidia_api_key()} if key]


def is_digitalocean_inference_endpoint() -> bool:
    return "inference.do-ai.run" in get_openai_compatible_base_url().lower()


def get_embedding_check_ctx_length() -> bool:
    raw = os.getenv("EMBEDDING_CHECK_CTX_LENGTH")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    # DigitalOcean's OpenAI-compatible embedding endpoint expects strings, while
    # LangChain's context-length checker may send token-id arrays.
    return not is_digitalocean_inference_endpoint()


def get_pydo_client() -> Client:
    token = get_model_access_key()
    if not token:
        raise RuntimeError("未找到 MODEL_ACCESS_KEY / OPENAI_API_KEY")
    return Client(token=token)
