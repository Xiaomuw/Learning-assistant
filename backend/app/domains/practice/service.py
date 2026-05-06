"""Practice domain façade.

题库推荐、AI 出题、MCQ 判题、attempt/记忆更新和导入流程已经拆到
专门子模块。保留本文件作为稳定导入入口，避免调用方一次性迁移。
"""

from __future__ import annotations

from app.domains.practice.attempts import record_practice_attempt_and_update_memory
from app.domains.practice.common import (
    OPTION_KEYS,
    determine_difficulty,
    infer_topic_from_question,
    normalize_quiz_item,
)
from app.domains.practice.generation import (
    build_mixed_practice_items,
    build_mixed_practice_items_with_status,
    build_recommended_practice_items,
)
from app.domains.practice.importer import import_question_bank_file
from app.domains.practice.mcq import solve_mcq_question
from app.domains.practice.quiz_flow import (
    build_quiz_final_answer,
    build_quiz_generation_context,
    build_quiz_plan_from_state,
    evaluate_quiz_quality,
    extract_quiz_knowledge_points,
    generate_quiz_items_from_context,
)
from app.domains.practice.quiz_request import (
    build_quiz_clarification_panel,
    context_from_practice_question,
    resolve_quiz_request,
)
from app.domains.practice.schemas import (
    GeneratedQuizItemOutput,
    GeneratedQuizListOutput,
    McqSolveOutput,
    QuizOptionOutput,
)

__all__ = [
    "OPTION_KEYS",
    "GeneratedQuizItemOutput",
    "GeneratedQuizListOutput",
    "McqSolveOutput",
    "QuizOptionOutput",
    "build_mixed_practice_items",
    "build_mixed_practice_items_with_status",
    "build_recommended_practice_items",
    "determine_difficulty",
    "import_question_bank_file",
    "infer_topic_from_question",
    "normalize_quiz_item",
    "record_practice_attempt_and_update_memory",
    "solve_mcq_question",
    "build_quiz_final_answer",
    "build_quiz_generation_context",
    "build_quiz_plan_from_state",
    "evaluate_quiz_quality",
    "extract_quiz_knowledge_points",
    "generate_quiz_items_from_context",
    "resolve_quiz_request",
    "build_quiz_clarification_panel",
    "context_from_practice_question",
]
