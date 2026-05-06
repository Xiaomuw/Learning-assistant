from __future__ import annotations

from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL, get_chat_llm


def get_generation_llm(
    temperature: float = 0.4,
    *,
    model_name: str | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
):
    return get_chat_llm(
        default_model=DEFAULT_CHAT_MODEL,
        temperature=temperature,
        model_override=model_name,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
