from __future__ import annotations

from pydantic import BaseModel, Field


class QAGraphInput(BaseModel):
    question: str = Field(min_length=1)
    user_id: str
    notebook_id: str | None = None
    source_policy: str = "open_tools"


class QAGraphOutput(BaseModel):
    answer: str = ""
    final_response: dict = Field(default_factory=dict)
    learning_event_ids: list[str] = Field(default_factory=list)
