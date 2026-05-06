"""Shared LLM model capability contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelProfile:
    model_id: str
    provider: str
    family: str
    supports_tool_calling: bool
    supports_structured_output: bool
    context_window: int
    supported_modalities: tuple[str, ...] = ("text",)
    max_output_tokens: int = 4096

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["supported_modalities"] = list(self.supported_modalities)
        return payload

