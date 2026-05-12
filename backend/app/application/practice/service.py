from __future__ import annotations

from typing import Callable

from loguru import logger

from app.application.practice.graph_facts import (
    update_graph_mastery_from_practice_attempt,
)
from app.domains.memory.service import build_request_context
from app.domains.practice.attempts import (
    PracticeAttemptFinalization,
    finalize_practice_attempt_analysis,
    record_practice_attempt_immediate,
)
from app.domains.practice.service import (
    build_recommended_practice_items,
    record_practice_attempt_and_update_memory,
)
from app.domains.practice.llm import resolve_practice_generation_model
from app.infrastructure.db.repositories.practice import (
    claim_practice_attempt_finalization_job,
    complete_practice_attempt_finalization_job,
    fail_practice_attempt_finalization_job,
    get_practice_attempt_record_by_id,
    list_due_practice_attempt_finalization_jobs,
)
from app.infrastructure.db.repositories.subjects import get_subject_record
from app.shared.schemas.contracts import PracticeRecommendation, PracticeRecommendationsResult, PracticeSubmissionResult
from app.shared.schemas.subject import DEFAULT_SUBJECTS, normalize_subject_id


def get_recommendations(*, user_id: str, subject_id: str | None, limit: int) -> PracticeRecommendationsResult:
    context = build_request_context(user_id, "")
    normalized_subject_id = normalize_subject_id(subject_id)
    subject = get_subject_record(normalized_subject_id)
    subject_name = subject.name if subject else str(DEFAULT_SUBJECTS[0]["name"])
    items = build_recommended_practice_items(
        user_id=user_id,
        subject_id=normalized_subject_id,
        subject_name=subject_name,
        user_style_name="",
        user_style_prompt="",
        short_term_context=context["short_term_context"],
        session_memory_context=context["session_memory_context"],
        long_term_context=context["long_term_context"],
        limit=limit,
        model_name=resolve_practice_generation_model(),
    )
    return PracticeRecommendationsResult(
        subject_id=normalized_subject_id,
        items=[PracticeRecommendation.model_validate(item) for item in items],
    )


def submit_attempt(
    *,
    user_id: str,
    session_id: str,
    subject_id: str,
    quiz_item: PracticeRecommendation,
    selected_option: str,
    schedule_finalizer: Callable[[str], None] | None = None,
) -> PracticeSubmissionResult:
    subject_id = normalize_subject_id(subject_id)
    if schedule_finalizer is not None:
        result, finalization = record_practice_attempt_immediate(
            user_id=user_id,
            session_id=session_id,
            subject_id=subject_id,
            quiz_item=quiz_item,
            selected_option=selected_option,
            durable_finalizer=True,
        )
        if finalization is not None and finalization.job_id:
            schedule_finalizer(finalization.job_id)
        return result

    result = record_practice_attempt_and_update_memory(
        user_id=user_id,
        session_id=session_id,
        subject_id=subject_id,
        quiz_item=quiz_item,
        selected_option=selected_option,
        graph_mastery_update=update_graph_mastery_from_practice_attempt,
    )
    return result


def finalize_attempt_analysis(finalization: PracticeAttemptFinalization) -> None:
    try:
        result = finalize_practice_attempt_analysis(
            finalization,
            graph_mastery_update=update_graph_mastery_from_practice_attempt,
        )
        if result is None or result.duplicate_submission:
            return
    except Exception as exc:  # pragma: no cover - 后台任务不可影响判题结果
        logger.exception("后台刷题学习画像更新失败: {}", exc.__class__.__name__)


FinalizerJobStatus = str


def finalize_attempt_analysis_job(job_id: str) -> FinalizerJobStatus:
    job = claim_practice_attempt_finalization_job(job_id)
    if job is None:
        return "skipped"
    try:
        finalization = _finalization_from_job(job)
        if finalization is None:
            return fail_practice_attempt_finalization_job(job_id, "legacy_attempt_missing")
        result = finalize_practice_attempt_analysis(
            finalization,
            graph_mastery_update=update_graph_mastery_from_practice_attempt,
        )
        if result is None:
            return fail_practice_attempt_finalization_job(job_id, "finalizer_returned_none")
        complete_practice_attempt_finalization_job(job_id)
        return "completed"
    except Exception as exc:  # pragma: no cover - 后台任务不可影响接口响应
        logger.exception("后台刷题学习画像 job 失败: {}", exc.__class__.__name__)
        return fail_practice_attempt_finalization_job(job_id, exc.__class__.__name__)


def run_due_practice_attempt_finalization_jobs(limit: int = 20) -> dict[str, int]:
    jobs = list_due_practice_attempt_finalization_jobs(limit=limit)
    summary = {
        "due": len(jobs),
        "claimed": 0,
        "completed": 0,
        "failed": 0,
        "dead": 0,
        "skipped": 0,
    }
    for job in jobs:
        job_id = str(job.get("job_id") or job.get("id") or "").strip()
        if not job_id:
            summary["skipped"] += 1
            continue
        status = finalize_attempt_analysis_job(job_id)
        if status != "skipped":
            summary["claimed"] += 1
        if status in summary:
            summary[status] += 1
        else:
            summary["failed"] += 1
    return summary


def _finalization_from_job(job: dict) -> PracticeAttemptFinalization | None:
    legacy_attempt_id = str(job.get("legacy_attempt_id") or "").strip()
    if not legacy_attempt_id:
        return None
    record = get_practice_attempt_record_by_id(legacy_attempt_id)
    if record is None:
        return None
    quiz_item = PracticeRecommendation.model_validate(record.question_snapshot)
    return PracticeAttemptFinalization(
        user_id=record.user_id,
        session_id=record.session_id,
        subject_id=record.subject_id,
        quiz_item=quiz_item,
        selected_option=record.selected_option,
        legacy_attempt=record.model_dump(),
        job_id=str(job.get("job_id") or job.get("id") or ""),
    )
