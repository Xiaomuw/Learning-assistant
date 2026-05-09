"""
LLM Model Profile
=================
静态维护模型能力画像，供主问答 runtime 做能力感知决策。
"""

from __future__ import annotations

import os
from dataclasses import replace

from app.shared.schemas.model_profile import ModelProfile


MODEL_METADATA_RULES = [
    ("openai-gpt-", "OpenAI", "GPT"),
    ("openai-o", "OpenAI", "Reasoning"),
    ("anthropic-claude-", "Anthropic", "Claude"),
    ("z-ai/glm", "NVIDIA", "GLM"),
    ("google-gemini", "Google", "Gemini"),
    ("gemini", "Google", "Gemini"),
    ("alibaba-qwen", "Alibaba", "Qwen"),
    ("qwen", "Alibaba", "Qwen"),
    ("deepseek-v4", "DeepSeek", "V4"),
    ("deepseek", "DeepSeek", "DeepSeek"),
    ("glm", "Zhipu", "GLM"),
    ("kimi", "Moonshot", "Kimi"),
    ("llama", "Meta", "Llama"),
    ("minimax", "MiniMax", "MiniMax"),
    ("nvidia", "NVIDIA", "Nemotron"),
    ("arcee", "Arcee", "Arcee"),
]


EXACT_MODEL_PROFILES: dict[str, ModelProfile] = {
    "openai-gpt-4.1": ModelProfile(
        model_id="openai-gpt-4.1",
        provider="OpenAI",
        family="GPT",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=1_000_000,
        supported_modalities=("text", "image"),
        max_output_tokens=32_768,
    ),
    "anthropic-claude-3-haiku-20240306": ModelProfile(
        model_id="anthropic-claude-3-haiku-20240306",
        provider="Anthropic",
        family="Claude",
        supports_tool_calling=False,
        supports_structured_output=False,
        context_window=200_000,
        supported_modalities=("text",),
        max_output_tokens=4_096,
    ),
    "openai-gpt-oss-20b": ModelProfile(
        model_id="openai-gpt-oss-20b",
        provider="OpenAI",
        family="GPT",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=128_000,
        supported_modalities=("text", "image"),
        max_output_tokens=16_384,
    ),
    "openai-gpt-oss-120b": ModelProfile(
        model_id="openai-gpt-oss-120b",
        provider="OpenAI",
        family="GPT",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=128_000,
        supported_modalities=("text", "image"),
        max_output_tokens=16_384,
    ),
    "openai-gpt-4o": ModelProfile(
        model_id="openai-gpt-4o",
        provider="OpenAI",
        family="GPT",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=128_000,
        supported_modalities=("text", "image"),
        max_output_tokens=16_384,
    ),
    "openai-gpt-4o-mini": ModelProfile(
        model_id="openai-gpt-4o-mini",
        provider="OpenAI",
        family="GPT",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=128_000,
        supported_modalities=("text", "image"),
        max_output_tokens=16_384,
    ),
    "google-gemini-2.5-pro": ModelProfile(
        model_id="google-gemini-2.5-pro",
        provider="Google",
        family="Gemini",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=1_000_000,
        supported_modalities=("text", "image"),
        max_output_tokens=8_192,
    ),
    "google-gemini-2.5-flash": ModelProfile(
        model_id="google-gemini-2.5-flash",
        provider="Google",
        family="Gemini",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=1_000_000,
        supported_modalities=("text", "image"),
        max_output_tokens=8_192,
    ),
    "z-ai/glm4.7": ModelProfile(
        model_id="z-ai/glm4.7",
        provider="NVIDIA",
        family="GLM",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=131_072,
        supported_modalities=("text",),
        max_output_tokens=16_384,
    ),
    "deepseek-v4-pro": ModelProfile(
        model_id="deepseek-v4-pro",
        provider="DeepSeek",
        family="V4",
        supports_tool_calling=True,
        supports_structured_output=False,
        context_window=1_000_000,
        supported_modalities=("text",),
        max_output_tokens=384_000,
    ),
    "deepseek-v4-flash": ModelProfile(
        model_id="deepseek-v4-flash",
        provider="DeepSeek",
        family="V4",
        supports_tool_calling=True,
        supports_structured_output=False,
        context_window=1_000_000,
        supported_modalities=("text",),
        max_output_tokens=384_000,
    ),
}


FAMILY_DEFAULTS: dict[str, ModelProfile] = {
    "GPT": ModelProfile(
        model_id="gpt-family-default",
        provider="OpenAI",
        family="GPT",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=128_000,
        supported_modalities=("text", "image"),
        max_output_tokens=16_384,
    ),
    "Reasoning": ModelProfile(
        model_id="reasoning-family-default",
        provider="OpenAI",
        family="Reasoning",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=200_000,
        supported_modalities=("text",),
        max_output_tokens=16_384,
    ),
    "Gemini": ModelProfile(
        model_id="gemini-family-default",
        provider="Google",
        family="Gemini",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=1_000_000,
        supported_modalities=("text", "image"),
        max_output_tokens=8_192,
    ),
    "Qwen": ModelProfile(
        model_id="qwen-family-default",
        provider="Alibaba",
        family="Qwen",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=128_000,
        supported_modalities=("text",),
        max_output_tokens=8_192,
    ),
    "GLM": ModelProfile(
        model_id="glm-family-default",
        provider="Zhipu",
        family="GLM",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=128_000,
        supported_modalities=("text",),
        max_output_tokens=8_192,
    ),
    "Kimi": ModelProfile(
        model_id="kimi-family-default",
        provider="Moonshot",
        family="Kimi",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=128_000,
        supported_modalities=("text",),
        max_output_tokens=8_192,
    ),
    "Llama": ModelProfile(
        model_id="llama-family-default",
        provider="Meta",
        family="Llama",
        supports_tool_calling=False,
        supports_structured_output=False,
        context_window=128_000,
        supported_modalities=("text",),
        max_output_tokens=4_096,
    ),
    "V4": ModelProfile(
        model_id="deepseek-v4-family-default",
        provider="DeepSeek",
        family="V4",
        supports_tool_calling=True,
        supports_structured_output=True,
        context_window=1_000_000,
        supported_modalities=("text",),
        max_output_tokens=384_000,
    ),
    "DeepSeek": ModelProfile(
        model_id="deepseek-family-default",
        provider="DeepSeek",
        family="DeepSeek",
        supports_tool_calling=False,
        supports_structured_output=False,
        context_window=128_000,
        supported_modalities=("text",),
        max_output_tokens=4_096,
    ),
    "Claude": ModelProfile(
        model_id="claude-family-default",
        provider="Anthropic",
        family="Claude",
        supports_tool_calling=False,
        supports_structured_output=False,
        context_window=200_000,
        supported_modalities=("text",),
        max_output_tokens=4_096,
    ),
}


UNKNOWN_MODEL_PROFILE = ModelProfile(
    model_id="unknown-model",
    provider="Other",
    family="Other",
    supports_tool_calling=False,
    supports_structured_output=False,
    context_window=16_000,
    supported_modalities=("text",),
    max_output_tokens=2_048,
)


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_digital_ocean_compatible_endpoint() -> bool:
    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip().lower()
    return "inference.do-ai.run" in base_url


def _apply_endpoint_overrides(profile: ModelProfile) -> ModelProfile:
    """Apply runtime capability overrides for OpenAI-compatible providers.

    DigitalOcean's inference endpoint is OpenAI-compatible for basic chat, but
    not all hosted models accept LangChain's native tool/structured payloads.
    Keep those capabilities opt-in so one unsupported request shape does not
    take down the whole Q&A flow.
    """
    if profile.provider == "NVIDIA":
        return replace(
            profile,
            supports_tool_calling=profile.supports_tool_calling
            and _env_flag("NVIDIA_ENABLE_TOOL_CALLING", default=False),
            supports_structured_output=profile.supports_structured_output
            and _env_flag("NVIDIA_ENABLE_STRUCTURED_OUTPUT", default=False),
        )

    if not _is_digital_ocean_compatible_endpoint():
        return profile

    return replace(
        profile,
        supports_tool_calling=profile.supports_tool_calling
        and _env_flag("LLM_ENABLE_TOOL_CALLING", default=False),
        supports_structured_output=profile.supports_structured_output
        and _env_flag("LLM_ENABLE_STRUCTURED_OUTPUT", default=False),
    )


def _infer_provider_family(model_id: str) -> tuple[str, str]:
    normalized = (model_id or "").lower()
    for prefix, provider, family in MODEL_METADATA_RULES:
        if normalized.startswith(prefix):
            return provider, family
    return UNKNOWN_MODEL_PROFILE.provider, UNKNOWN_MODEL_PROFILE.family


def get_model_profile(model_name: str | None) -> ModelProfile:
    normalized = (model_name or "").strip()
    if not normalized:
        return UNKNOWN_MODEL_PROFILE

    exact = EXACT_MODEL_PROFILES.get(normalized)
    if exact:
        return _apply_endpoint_overrides(exact)

    provider, family = _infer_provider_family(normalized)
    family_default = FAMILY_DEFAULTS.get(family)
    if family_default:
        return _apply_endpoint_overrides(ModelProfile(
            model_id=normalized,
            provider=provider,
            family=family,
            supports_tool_calling=family_default.supports_tool_calling,
            supports_structured_output=family_default.supports_structured_output,
            context_window=family_default.context_window,
            supported_modalities=family_default.supported_modalities,
            max_output_tokens=family_default.max_output_tokens,
        ))

    return _apply_endpoint_overrides(ModelProfile(
        model_id=normalized,
        provider=provider,
        family=family,
        supports_tool_calling=False,
        supports_structured_output=False,
        context_window=UNKNOWN_MODEL_PROFILE.context_window,
        supported_modalities=UNKNOWN_MODEL_PROFILE.supported_modalities,
        max_output_tokens=UNKNOWN_MODEL_PROFILE.max_output_tokens,
    ))
