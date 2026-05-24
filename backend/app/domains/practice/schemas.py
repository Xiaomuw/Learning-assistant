from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class QuizOptionOutput(BaseModel):
    key: Literal["A", "B", "C", "D"]
    text: str = Field(min_length=1, max_length=300)


class GeneratedQuizItemOutput(BaseModel):
    difficulty: Literal["基础", "变式", "易错"]
    question: str = Field(min_length=8, max_length=1200)
    options: list[QuizOptionOutput] = Field(min_length=4, max_length=4)
    correct_option: Literal["A", "B", "C", "D"]
    explanation: str = Field(min_length=8, max_length=2000)
    option_rationales: dict[str, str] = Field(default_factory=dict)
    knowledge_point: str = Field(min_length=1, max_length=120)
    hint: str = Field(default="", max_length=300)


class GeneratedQuizListOutput(BaseModel):
    items: list[GeneratedQuizItemOutput] = Field(min_length=1, max_length=6)

    @model_validator(mode="before")
    @classmethod
    def normalize_model_output(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"items": data}
        if isinstance(data, dict) and "items" not in data and _looks_like_quiz_item(data):
            return {"items": [data]}
        return data


def _looks_like_quiz_item(data: dict[str, Any]) -> bool:
    return bool(
        {"question", "options", "correct_option", "explanation", "knowledge_point"}
        .issubset(data.keys())
    )


class McqSolveOutput(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    parsed_question: str = Field(min_length=1, max_length=1200)
    parsed_options: list[QuizOptionOutput] = Field(min_length=4, max_length=4)
    correct_option: Literal["A", "B", "C", "D"]
    explanation: str = Field(min_length=8, max_length=2000)
    option_rationales: dict[str, str] = Field(default_factory=dict)
    mistakes: str = Field(default="", max_length=300)
    similar: list[str] = Field(default_factory=list, min_length=2, max_length=3)
