from __future__ import annotations

import time
from typing import Any, Callable

from loguru import logger

from app.infrastructure.llm.config import DEFAULT_CHAT_MODEL, get_fallback_chat_model

MODEL_CACHE_TTL_SECONDS = 300

BLOCKED_MODEL_PREFIXES = ("openai-gpt-image-", "gpt-image-")
NON_CHAT_MODEL_KEYWORDS = (
    "embedding",
    "mini-lm",
    "mpnet",
    "gte-",
    "t2v",
)

MODEL_METADATA_RULES = [
    ("openai-gpt-", "OpenAI", "GPT"),
    ("openai-o", "OpenAI", "Reasoning"),
    ("anthropic-claude-", "Anthropic", "Claude"),
    ("z-ai/glm", "NVIDIA", "GLM"),
    ("google-gemini", "Google", "Gemini"),
    ("gemini", "Google", "Gemini"),
    ("alibaba-qwen", "Alibaba", "Qwen"),
    ("qwen", "Alibaba", "Qwen"),
    ("deepseek", "DeepSeek", "DeepSeek"),
    ("glm", "Zhipu", "GLM"),
    ("kimi", "Moonshot", "Kimi"),
    ("llama", "Meta", "Llama"),
    ("minimax", "MiniMax", "MiniMax"),
    ("nvidia", "NVIDIA", "Nemotron"),
    ("arcee", "Arcee", "Arcee"),
]

PREFERRED_MODEL_ORDER = [
    "openai-gpt-4.1",
    "anthropic-claude-3-haiku-20240306",
    "openai-gpt-5",
    "z-ai/glm4.7",
    "openai-gpt-oss-20b",
    "openai-gpt-oss-120b",
    "openai-gpt-4o",
    "openai-gpt-4o-mini",
    "openai-gpt-5-mini",
    "openai-gpt-5.4-mini",
    "openai-gpt-5.4",
    "google-gemini-2.5-pro",
    "google-gemini-2.5-flash",
    "alibaba-qwen3-32b",
    "glm-5",
    "kimi-k2.5",
    "llama3.3-70b-instruct",
    "deepseek-r1-distill-llama-70b",
]

_MODEL_CANDIDATE_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "models": [],
}
_MODEL_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "models": [],
    "last_successful_models": [],
}
_MODEL_ACCESS_CACHE: dict[str, dict[str, Any]] = {}


def _is_selectable_chat_model(model_id: str) -> bool:
    normalized = model_id.lower()

    if any(normalized.startswith(prefix) for prefix in BLOCKED_MODEL_PREFIXES):
        return False

    if any(keyword in normalized for keyword in NON_CHAT_MODEL_KEYWORDS):
        return False

    return True


def _titleize_token(token: str) -> str:
    if token.isupper() or token.isdigit():
        return token
    return token.capitalize()


def _prettify_model_label(model_id: str, family: str) -> str:
    if family == "GPT":
        return (
            model_id.replace("openai-", "")
            .replace("gpt-", "GPT-")
            .replace("oss", "OSS")
        )
    if family == "Claude":
        if model_id == "anthropic-claude-3-haiku-20240306":
            return "Claude 3 Haiku"
        return model_id.replace("anthropic-", "").replace("claude-", "Claude ")
    if family == "Gemini":
        return model_id.replace("google-", "").replace("gemini-", "Gemini-")
    if family == "Qwen":
        return model_id.replace("alibaba-", "").replace("qwen", "Qwen")
    if family == "GLM":
        if model_id.lower() == "z-ai/glm4.7":
            return "GLM-4.7"
        return model_id.upper()
    if family == "Kimi":
        return model_id.replace("kimi-", "Kimi-")
    if family == "Llama":
        return model_id.replace("llama", "Llama ")
    if family == "DeepSeek":
        return model_id.replace("deepseek-", "DeepSeek-")

    return " ".join(_titleize_token(token) for token in model_id.split("-"))


def build_model_option(model_id: str) -> dict[str, str] | None:
    if not _is_selectable_chat_model(model_id):
        return None

    normalized = model_id.lower()
    provider = "Other"
    family = "Other"

    for prefix, rule_provider, rule_family in MODEL_METADATA_RULES:
        if normalized.startswith(prefix):
            provider = rule_provider
            family = rule_family
            break

    return {
        "id": model_id,
        "label": _prettify_model_label(model_id, family),
        "provider": provider,
        "family": family,
    }


def _sort_model_options(models: list[dict[str, str]]) -> list[dict[str, str]]:
    order = {model_id: index for index, model_id in enumerate(PREFERRED_MODEL_ORDER)}
    return sorted(
        models,
        key=lambda item: (
            order.get(item["id"], len(PREFERRED_MODEL_ORDER) + 1),
            item["provider"],
            item["label"],
        ),
    )


def _copy_model_options(models: list[dict[str, str]]) -> list[dict[str, str]]:
    return [dict(item) for item in models]


def _deduplicate_model_options(model_options: list[dict[str, str]]) -> list[dict[str, str]]:
    deduplicated: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for option in model_options:
        if option["id"] in seen_ids:
            continue
        seen_ids.add(option["id"])
        deduplicated.append(option)
    return deduplicated


def _load_candidate_chat_models(
    *,
    force_refresh: bool = False,
    remote_client_factory: Callable[[], Any],
) -> list[dict[str, str]]:
    now = time.time()
    if (
        not force_refresh
        and _MODEL_CANDIDATE_CACHE["models"]
        and now < float(_MODEL_CANDIDATE_CACHE["expires_at"])
    ):
        return _copy_model_options(_MODEL_CANDIDATE_CACHE["models"])

    remote_models = remote_client_factory().inference.list_models().get("data", [])
    model_options: list[dict[str, str]] = []
    for item in remote_models:
        model_id = item.get("id", "")
        option = build_model_option(model_id)
        if option:
            model_options.append(option)

    deduplicated = _sort_model_options(_deduplicate_model_options(model_options))
    _MODEL_CANDIDATE_CACHE["models"] = _copy_model_options(deduplicated)
    _MODEL_CANDIDATE_CACHE["expires_at"] = now + MODEL_CACHE_TTL_SECONDS
    return _copy_model_options(deduplicated)


def _get_cached_model_access_result(
    model_id: str,
    *,
    force_refresh: bool = False,
    validate_model_access: Callable[[str], tuple[bool, str | None]],
) -> tuple[bool, str | None]:
    now = time.time()
    cached = _MODEL_ACCESS_CACHE.get(model_id)
    if (
        cached
        and not force_refresh
        and now < float(cached.get("expires_at", 0.0))
    ):
        return bool(cached.get("usable")), cached.get("error")

    is_valid, error_message = validate_model_access(model_id)
    _MODEL_ACCESS_CACHE[model_id] = {
        "usable": is_valid,
        "error": error_message,
        "expires_at": now + MODEL_CACHE_TTL_SECONDS,
    }
    return is_valid, error_message


def _get_last_successful_model_cache() -> list[dict[str, str]]:
    return _copy_model_options(_MODEL_CACHE["last_successful_models"])


def get_cached_selectable_chat_models() -> list[dict[str, str]]:
    """Return already verified model options without touching the network."""
    now = time.time()
    if _MODEL_CACHE["models"] and now < float(_MODEL_CACHE["expires_at"]):
        return _copy_model_options(_MODEL_CACHE["models"])
    return _get_last_successful_model_cache()


def list_configured_chat_models() -> list[dict[str, str]]:
    """Return the product-supported chat models without probing providers."""
    configured_ids = [DEFAULT_CHAT_MODEL, get_fallback_chat_model()]
    return _sort_model_options(
        _deduplicate_model_options(
            [option for model_id in configured_ids if (option := build_model_option(model_id))]
        )
    )


def list_selectable_chat_models(
    *,
    force_refresh: bool = False,
    remote_client_factory: Callable[[], Any],
    validate_model_access: Callable[[str], tuple[bool, str | None]],
) -> list[dict[str, str]]:
    now = time.time()
    if (
        not force_refresh
        and _MODEL_CACHE["models"]
        and now < float(_MODEL_CACHE["expires_at"])
    ):
        return _copy_model_options(_MODEL_CACHE["models"])

    try:
        model_options = _load_candidate_chat_models(
            force_refresh=force_refresh,
            remote_client_factory=remote_client_factory,
        )
    except Exception as exc:
        cached_models = _get_last_successful_model_cache()
        if cached_models:
            logger.warning(f"⚠️ 拉取远程模型列表失败，回退到最近一次已验证可用模型缓存: {exc}")
            return cached_models
        logger.warning(f"⚠️ 拉取远程模型列表失败，且没有任何已验证模型缓存: {exc}")
        return []

    available_models: list[dict[str, str]] = []
    for option in model_options:
        is_valid, error_message = _get_cached_model_access_result(
            option["id"],
            force_refresh=force_refresh,
            validate_model_access=validate_model_access,
        )
        if is_valid:
            available_models.append(dict(option))
            continue
        logger.info(f"🚫 模型 {option['id']} 已从切换列表隐藏: {error_message}")

    available_models = _sort_model_options(_deduplicate_model_options(available_models))
    if available_models:
        _MODEL_CACHE["models"] = _copy_model_options(available_models)
        _MODEL_CACHE["last_successful_models"] = _copy_model_options(available_models)
        _MODEL_CACHE["expires_at"] = now + MODEL_CACHE_TTL_SECONDS
    else:
        _MODEL_CACHE["models"] = []
        _MODEL_CACHE["expires_at"] = 0.0
    return _copy_model_options(available_models)
