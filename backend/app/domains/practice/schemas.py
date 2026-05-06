from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class McqSolveOutput(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    parsed_question: str = Field(min_length=1, max_length=1200)
    parsed_options: list[QuizOptionOutput] = Field(min_length=4, max_length=4)
    correct_option: Literal["A", "B", "C", "D"]
    explanation: str = Field(min_length=8, max_length=2000)
    option_rationales: dict[str, str] = Field(default_factory=dict)
    mistakes: str = Field(default="", max_length=300)
    similar: list[str] = Field(default_factory=list, min_length=2, max_length=3)
