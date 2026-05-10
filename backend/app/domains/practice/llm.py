from __future__ import annotations

from app.infrastructure.llm.config import get_practice_generation_model
from app.infrastructure.llm.provider import get_chat_llm


def resolve_practice_generation_model(model_name: str | None = None) -> str:
    return (model_name or get_practice_generation_model()).strip() or get_practice_generation_model()


def get_generation_llm(
    temperature: float = 0.4,
    *,
    model_name: str | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
):
    return get_chat_llm(
        default_model=get_practice_generation_model(),
        temperature=temperature,
        model_override=resolve_practice_generation_model(model_name),
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
