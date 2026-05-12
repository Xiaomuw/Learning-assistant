from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


OptionKey = Literal["A", "B", "C", "D"]


class SourceRef(BaseModel):
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    evidence_id: str = ""
    title: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class AnswerOption(BaseModel):
    key: OptionKey
    text: str = Field(min_length=1, max_length=300)


class AnswerKey(BaseModel):
    correct_option: OptionKey
    correct_option_text: str = Field(min_length=1, max_length=300)
    explanation: str = Field(min_length=8, max_length=2000)
    option_rationales: dict[OptionKey, str] = Field(default_factory=dict)


class Rubric(BaseModel):
    criteria: list[str] = Field(default_factory=list)
    full_credit: str = Field(min_length=1)
    common_misconceptions: list[str] = Field(default_factory=list)


class ItemBlueprint(BaseModel):
    primary_concept_id: str = Field(min_length=1)
    concept_name: str = Field(min_length=1)
    difficulty: str = "基础"
    item_type: Literal["single_choice"] = "single_choice"
    count: int = Field(default=1, ge=1, le=10)
    source_policy: str = "open_tools"
    constraints: dict[str, str] = Field(default_factory=dict)


class QuestionCandidate(BaseModel):
    stem: str = Field(min_length=8, max_length=1200)
    options: list[AnswerOption] = Field(min_length=4, max_length=4)
    primary_concept_id: str = Field(min_length=1)
    difficulty: str = "基础"
    source_refs: list[SourceRef] = Field(min_length=1)
    answer_key: AnswerKey
    rubric: Rubric
    generation_source: str = "deterministic_adapter"


class SolverVerification(BaseModel):
    passed: bool = False
    selected_option: OptionKey | None = None
    issues: list[str] = Field(default_factory=list)
    verifier_source: str = "rule_based"


class DedupeReport(BaseModel):
    passed: bool = True
    duplicate_question_ids: list[str] = Field(default_factory=list)


class DifficultyCalibration(BaseModel):
    passed: bool = True
    requested_difficulty: str = "基础"
    calibrated_difficulty: str = "基础"
    issues: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    passed: bool = False
    issues: list[str] = Field(default_factory=list)
    checked_count: int = 0
    expected_count: int = 0
    solver_verifier: SolverVerification = Field(default_factory=SolverVerification)
    reviewer: dict[str, str | bool | list[str]] = Field(default_factory=dict)
    dedupe_checker: DedupeReport = Field(default_factory=DedupeReport)
    difficulty_calibrator: DifficultyCalibration = Field(default_factory=DifficultyCalibration)
    retry_count: int = 0


class QuestionItem(BaseModel):
    id: str = ""
    item_type: Literal["single_choice"] = "single_choice"
    stem: str = Field(min_length=8, max_length=1200)
    options: list[AnswerOption] = Field(min_length=4, max_length=4)
    primary_concept_id: str = Field(min_length=1)
    difficulty: str = "基础"
    source_refs: list[SourceRef] = Field(min_length=1)
    answer_key: AnswerKey
    rubric: Rubric
    quality_report: QualityReport
    generation_source: str = "deterministic_adapter"


class QuestionGenerationInput(BaseModel):
    user_id: str
    concepts: list[str] = Field(default_factory=list)
    difficulty: str = "基础"
    count: int = Field(default=1, ge=1, le=10)


class QuestionGenerationOutput(BaseModel):
    question_item_ids: list[str] = Field(default_factory=list)
    quality_passed: bool = False
    learning_event_ids: list[str] = Field(default_factory=list)
