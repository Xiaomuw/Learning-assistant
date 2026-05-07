from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.orchestration.graphs.question_generation.adapter import QuestionCandidateGenerator
from app.orchestration.graphs.question_generation.schemas import (
    DedupeReport,
    DifficultyCalibration,
    ItemBlueprint,
    QualityReport,
    QuestionCandidate,
    QuestionItem,
    SolverVerification,
    SourceRef,
)
from app.orchestration.graphs.question_generation.state import QuestionGenerationState
from app.orchestration.graphs.shared.schemas import (
    ConceptRef,
    FinalResponse,
    GraphError,
    GraphErrorSeverity,
    GraphType,
    LearningEvent,
    LearningEventType,
    SourceLevel,
    SourcePolicy,
    new_event_id,
)
from app.persistence.interfaces import LearningEventRepository, QuestionItemRepository

OPTION_KEYS = ("A", "B", "C", "D")
ALLOWED_QGEN_EVENTS = {
    LearningEventType.QUESTION_GENERATED.value,
    LearningEventType.QUESTION_REVIEWED.value,
    LearningEventType.QUESTION_GENERATION_DEGRADED.value,
    LearningEventType.QUESTION_GENERATION_FAILED.value,
}


def build_blueprint_node(state: QuestionGenerationState) -> dict[str, Any]:
    concept = _primary_concept(state)
    quiz_request = state.get("quiz_request") if isinstance(state.get("quiz_request"), dict) else {}
    count = _bounded_count(quiz_request.get("count") or state.get("count") or state.get("requested_count") or 1)
    status = dict(state.get("generation_status") or {})
    blueprint = ItemBlueprint(
        primary_concept_id=concept.concept_id or _stable_concept_id(concept.name),
        concept_name=concept.name,
        difficulty=_difficulty_label(str(quiz_request.get("difficulty") or state.get("difficulty") or state.get("target_difficulty") or "基础")),
        count=count,
        source_policy=str(state.get("source_policy") or SourcePolicy.OPEN_TOOLS.value),
        constraints={
            "item_type": "single_choice",
            "requested_topic": str(quiz_request.get("requested_topic") or ""),
            "active_topic": str(quiz_request.get("active_topic") or quiz_request.get("topic") or ""),
            "previous_topic": str(quiz_request.get("previous_topic") or ""),
            "subject_id": str(quiz_request.get("subject_id") or state.get("subject_id") or state.get("notebook_id") or ""),
        },
    )
    status.update(
        {
            "requested_count": count,
            "generated_count": int(status.get("generated_count") or 0),
            "persisted_count": int(status.get("persisted_count") or 0),
            "retry_count": int(status.get("retry_count") or 0),
            "active_topic": blueprint.concept_name,
            "requested_topic": str(quiz_request.get("requested_topic") or ""),
            "previous_topic": str(quiz_request.get("previous_topic") or ""),
        }
    )
    return {
        "generation_blueprint": blueprint.model_dump(mode="json"),
        "concepts": [concept.model_dump(mode="json")],
        "generation_status": status,
    }


def prepare_source_refs_node(state: QuestionGenerationState) -> dict[str, Any]:
    evidence_items = list(state.get("evidence") or [])
    source_refs: list[SourceRef] = []
    for index, item in enumerate(evidence_items, start=1):
        if hasattr(item, "model_dump"):
            item = item.model_dump(mode="json")
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("id") or f"evidence-{index}")
        source_type = str(item.get("source_type") or "notebook")
        source_id = str(item.get("source_id") or evidence_id)
        source_refs.append(
            SourceRef(
                source_type=source_type,
                source_id=source_id,
                evidence_id=evidence_id,
                title=str(item.get("metadata", {}).get("title") or ""),
                metadata={"origin": "state.evidence"},
            )
        )

    source_refs_degraded = not source_refs
    if source_refs_degraded:
        source_refs.append(
            SourceRef(
                source_type="generator",
                source_id="deterministic_adapter",
                metadata={"origin": "question_generation_adapter"},
            )
        )
    status = dict(state.get("generation_status") or {})
    status.update(
        {
            "source_ref_count": 0 if source_refs_degraded else len(source_refs),
            "source_refs_degraded": source_refs_degraded,
            "source_ref_policy": "generator_fallback" if source_refs_degraded else "evidence_grounded",
        }
    )
    return {
        "source_refs": [item.model_dump(mode="json") for item in source_refs],
        "generation_status": status,
    }


def make_generate_candidates_node(generator: QuestionCandidateGenerator):
    def generate_candidates_node(state: QuestionGenerationState) -> dict[str, Any]:
        blueprint = ItemBlueprint.model_validate(state.get("generation_blueprint") or {})
        source_refs = [SourceRef.model_validate(item) for item in list(state.get("source_refs") or [])]
        status = dict(state.get("generation_status") or {})
        errors = list(state.get("errors") or [])
        max_attempts = _bounded_retry_count(status.get("max_generation_attempts") or state.get("max_generation_attempts"))
        candidates: list[QuestionCandidate] = []
        adapter_status: dict[str, Any] = {"generation_source": generator.__class__.__name__, "generated_count": 0}
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                generation_runner = getattr(generator, "generate_with_status", None)
                if callable(generation_runner):
                    result = generation_runner(blueprint=blueprint, source_refs=source_refs)
                    candidates = list(getattr(result, "candidates", []) or [])
                    adapter_status = dict(getattr(result, "status", {}) or {})
                else:
                    candidates = generator.generate(blueprint=blueprint, source_refs=source_refs)
                    adapter_status = {
                        "generation_source": generator.__class__.__name__,
                        "generated_count": len(candidates),
                    }
                adapter_status["retry_count"] = attempt - 1
                if candidates:
                    break
            except Exception as exc:
                last_error = exc
                candidates = []
                adapter_status = {
                    "generation_source": generator.__class__.__name__,
                    "generated_count": 0,
                    "partial": True,
                    "degraded_reason": f"question candidate generator failed: {exc.__class__.__name__}",
                    "retry_count": attempt - 1,
                }

        if last_error is not None and not candidates:
            errors.append(
                GraphError(
                    code="question_generation_adapter_error",
                    message=last_error.__class__.__name__,
                    node="generate_candidates",
                    severity=GraphErrorSeverity.ERROR,
                ).model_dump(mode="json")
            )

        status.update(adapter_status)
        status["retry_count"] = max(
            int(status.get("retry_count") or 0),
            int(adapter_status.get("retry_count") or 0),
            int(status.get("quality_retry_count") or 0),
        )
        status["max_generation_attempts"] = max_attempts
        status["generated_count"] = len(candidates)
        if not candidates:
            status["partial"] = True
            status["empty_generation"] = True
            errors.append(
                GraphError(
                    code="question_generation_empty",
                    message="Question generation returned no candidates.",
                    node="generate_candidates",
                    severity=GraphErrorSeverity.WARNING,
                    metadata={
                        "requested_count": blueprint.count,
                        "generation_source": str(status.get("generation_source") or ""),
                    },
                ).model_dump(mode="json")
            )
        return {
            "question_candidates": [item.model_dump(mode="json") for item in candidates],
            "generation_status": status,
            "errors": errors,
        }

    return generate_candidates_node


def solver_verifier_node(state: QuestionGenerationState) -> dict[str, Any]:
    candidates = _candidate_list(state)
    issues: list[str] = []
    selected_option = None
    for index, candidate in enumerate(candidates, start=1):
        option_keys = [option.key for option in candidate.options]
        option_texts = [option.text.strip() for option in candidate.options]
        selected_option = candidate.answer_key.correct_option
        if option_keys != list(OPTION_KEYS):
            issues.append(f"第 {index} 题选项不是完整 A/B/C/D")
        if selected_option not in option_keys:
            issues.append(f"第 {index} 题答案不在选项中")
        if len(set(option_texts)) != len(option_texts):
            issues.append(f"第 {index} 题存在重复选项文本")
        correct_text = next((option.text for option in candidate.options if option.key == selected_option), "")
        if correct_text != candidate.answer_key.correct_option_text:
            issues.append(f"第 {index} 题 answer_key.correct_option_text 与选项不一致")

    report = SolverVerification(
        passed=not issues and bool(candidates),
        selected_option=selected_option,
        issues=issues,
    )
    return {"solver_report": report.model_dump(mode="json")}


def quality_reviewer_node(state: QuestionGenerationState) -> dict[str, Any]:
    blueprint = ItemBlueprint.model_validate(state.get("generation_blueprint") or {})
    candidates = _candidate_list(state)
    solver = SolverVerification.model_validate(state.get("solver_report") or {})
    status = dict(state.get("generation_status") or {})
    issues = list(solver.issues)
    topic_alignment_issues: list[str] = []

    if len(candidates) < blueprint.count:
        issues.append(f"题目数量不足: expected={blueprint.count}, actual={len(candidates)}")
    for index, candidate in enumerate(candidates, start=1):
        if not candidate.source_refs:
            issues.append(f"第 {index} 题缺少 source_refs")
        if candidate.primary_concept_id != blueprint.primary_concept_id:
            issues.append(f"第 {index} 题 primary_concept_id 不匹配")
        missing_rationales = [
            key for key in OPTION_KEYS if not candidate.answer_key.option_rationales.get(key, "").strip()
        ]
        if missing_rationales:
            issues.append(f"第 {index} 题缺少选项解析: {','.join(missing_rationales)}")
        if len(candidate.answer_key.explanation.strip()) < 8:
            issues.append(f"第 {index} 题缺少标准解析")
        if not candidate.rubric.criteria or not candidate.rubric.full_credit.strip():
            issues.append(f"第 {index} 题缺少 rubric")
        if blueprint.source_policy == SourcePolicy.NOTEBOOK_ONLY.value and not _grounded_in_notebook(candidate):
            issues.append(f"第 {index} 题不满足 notebook_only grounding")
        topic_issue = _topic_alignment_issue(blueprint, candidate, index)
        if topic_issue:
            topic_alignment_issues.append(topic_issue)

    issues.extend(topic_alignment_issues)
    topic_alignment_passed = not topic_alignment_issues
    retry_count = int(status.get("quality_retry_count") or 0)

    report = QualityReport(
        passed=not issues and solver.passed,
        issues=issues,
        checked_count=len(candidates),
        expected_count=blueprint.count,
        solver_verifier=solver,
        retry_count=retry_count,
        reviewer={
            "passed": not issues and solver.passed,
            "checks": [
                "structure",
                "answer_key",
                "rubric",
                "concept_alignment",
                "source_policy_grounding",
                "topic_alignment",
            ],
            "issues": issues,
            "topic_alignment_passed": topic_alignment_passed,
            "topic_alignment_reason": "pass" if topic_alignment_passed else "主题不一致",
        },
    )
    return {"quality_report": report.model_dump(mode="json")}


def route_after_quality_reviewer(state: QuestionGenerationState) -> str:
    report = QualityReport.model_validate(state.get("quality_report") or {})
    status = dict(state.get("generation_status") or {})
    retry_count = int(status.get("quality_retry_count") or 0)
    has_topic_mismatch = any("主题不一致" in issue for issue in report.issues)
    if not report.passed and has_topic_mismatch and retry_count < 1:
        return "retry"
    return "continue"


def prepare_quality_retry_node(state: QuestionGenerationState) -> dict[str, Any]:
    report = QualityReport.model_validate(state.get("quality_report") or {})
    status = dict(state.get("generation_status") or {})
    retry_count = int(status.get("quality_retry_count") or 0) + 1
    mismatch_reasons = [issue for issue in report.issues if "主题不一致" in issue]
    status.update(
        {
            "quality_retry_count": retry_count,
            "retry_count": retry_count,
            "quality_retry_reason": mismatch_reasons[0] if mismatch_reasons else "主题不一致，重新生成",
            "generated_count": 0,
        }
    )
    return {
        "question_candidates": [],
        "solver_report": {},
        "quality_report": {},
        "generation_status": status,
    }


def make_dedupe_checker_node(question_item_repository: QuestionItemRepository):
    def dedupe_checker_node(state: QuestionGenerationState) -> dict[str, Any]:
        candidates = _candidate_list(state)
        report = QualityReport.model_validate(state.get("quality_report") or {})
        duplicate_ids: list[str] = []
        status = dict(state.get("generation_status") or {})
        errors = list(state.get("errors") or [])
        for candidate in candidates:
            try:
                matches = question_item_repository.find_similar(candidate.model_dump(mode="json"), limit=5)
            except Exception as exc:
                status.update(
                    {
                        "dedupe_unavailable": True,
                        "dedupe_error_type": exc.__class__.__name__,
                    }
                )
                errors.append(
                    GraphError(
                        code="question_dedupe_unavailable",
                        message=exc.__class__.__name__,
                        node="dedupe_checker",
                        severity=GraphErrorSeverity.WARNING,
                    ).model_dump(mode="json")
                )
                matches = []
            duplicate_ids.extend(str(item.get("id") or item.get("question_id")) for item in matches if item)

        duplicate_ids = sorted({item for item in duplicate_ids if item})
        dedupe = DedupeReport(passed=not duplicate_ids, duplicate_question_ids=duplicate_ids)
        issues = list(report.issues)
        if duplicate_ids:
            issues.append(f"发现重复题目: {','.join(duplicate_ids)}")
        updated = report.model_copy(
            update={
                "passed": report.passed and dedupe.passed,
                "issues": issues,
                "dedupe_checker": dedupe,
            }
        )
        return {
            "quality_report": updated.model_dump(mode="json"),
            "generation_status": status,
            "errors": errors,
        }

    return dedupe_checker_node


def difficulty_calibrator_node(state: QuestionGenerationState) -> dict[str, Any]:
    blueprint = ItemBlueprint.model_validate(state.get("generation_blueprint") or {})
    candidates = _candidate_list(state)
    report = QualityReport.model_validate(state.get("quality_report") or {})
    issues = [
        f"第 {index} 题难度不匹配: expected={blueprint.difficulty}, actual={candidate.difficulty}"
        for index, candidate in enumerate(candidates, start=1)
        if candidate.difficulty != blueprint.difficulty
    ]
    calibration = DifficultyCalibration(
        passed=not issues,
        requested_difficulty=blueprint.difficulty,
        calibrated_difficulty=blueprint.difficulty,
        issues=issues,
    )
    updated_issues = [*report.issues, *issues]
    updated = report.model_copy(
        update={
            "passed": report.passed and calibration.passed,
            "issues": updated_issues,
            "difficulty_calibrator": calibration,
        }
    )
    return {"quality_report": updated.model_dump(mode="json")}


def make_persist_question_items_node(
    *,
    question_item_repository: QuestionItemRepository,
    learning_event_repository: LearningEventRepository | None = None,
):
    def persist_question_items_node(state: QuestionGenerationState) -> dict[str, Any]:
        report = QualityReport.model_validate(state.get("quality_report") or {})
        candidates = _candidate_list(state)
        item_ids: list[str] = []
        items: list[QuestionItem] = []
        events: list[LearningEvent] = []
        status = dict(state.get("generation_status") or {})
        errors = list(state.get("errors") or [])

        review_event = _learning_event(
            state,
            event_type=LearningEventType.QUESTION_REVIEWED.value,
            concept_id=_blueprint_concept_id(state),
            payload={
                "passed": report.passed,
                "issues": report.issues,
                "solver_verifier": report.solver_verifier.model_dump(mode="json"),
                "reviewer": report.reviewer,
                "retry_count": report.retry_count,
            },
        )
        events.append(review_event)

        if report.passed:
            if _is_degraded_generation(status):
                events.append(
                    _learning_event(
                        state,
                        event_type=LearningEventType.QUESTION_GENERATION_DEGRADED.value,
                        concept_id=_blueprint_concept_id(state),
                        payload={
                            "reason": _degraded_reason(status),
                            "source_refs_degraded": bool(status.get("source_refs_degraded", False)),
                            "fallback_count": int(status.get("fallback_count") or 0),
                            "partial": bool(status.get("partial", False)),
                            "generation_source": str(status.get("generation_source") or ""),
                        },
                    )
                )
            for candidate in candidates:
                item = QuestionItem(
                    id=f"qitem-{uuid4()}",
                    stem=candidate.stem,
                    options=candidate.options,
                    primary_concept_id=candidate.primary_concept_id,
                    difficulty=candidate.difficulty,
                    source_refs=candidate.source_refs,
                    answer_key=candidate.answer_key,
                    rubric=candidate.rubric,
                    quality_report=report,
                    generation_source=candidate.generation_source,
                )
                payload = item.model_dump(mode="json")
                try:
                    item_id = question_item_repository.create_question_item(payload)
                except Exception as exc:
                    item_id = item.id
                    status["persist_degraded"] = True
                    status["persist_error_type"] = exc.__class__.__name__
                    errors.append(
                        GraphError(
                            code="question_item_persist_unavailable",
                            message=exc.__class__.__name__,
                            node="persist_question_items",
                            severity=GraphErrorSeverity.WARNING,
                        ).model_dump(mode="json")
                    )
                item = item.model_copy(update={"id": item_id})
                item_ids.append(item_id)
                items.append(item)
                events.append(
                    _learning_event(
                        state,
                        event_type=LearningEventType.QUESTION_GENERATED.value,
                        concept_id=item.primary_concept_id,
                        payload={
                            "question_item_id": item_id,
                            "concept": item.primary_concept_id,
                            "difficulty": item.difficulty,
                            "source_refs": [ref.model_dump(mode="json") for ref in item.source_refs],
                            "generation_source": item.generation_source,
                        },
                    )
                )
        else:
            events.append(
                _learning_event(
                    state,
                    event_type=LearningEventType.QUESTION_GENERATION_FAILED.value,
                    concept_id=_blueprint_concept_id(state),
                    payload={
                        "issues": report.issues,
                        "persisted": False,
                        "graph_errors": list(state.get("errors") or []),
                    },
                )
            )

        for event in events:
            if learning_event_repository is not None:
                try:
                    learning_event_repository.append(event)
                except Exception as exc:
                    status["event_persist_degraded"] = True
                    status["event_persist_error_type"] = exc.__class__.__name__
                    errors.append(
                        GraphError(
                            code="question_event_persist_unavailable",
                            message=exc.__class__.__name__,
                            node="persist_question_items",
                            severity=GraphErrorSeverity.WARNING,
                        ).model_dump(mode="json")
                    )

        existing_events = list(state.get("learning_events") or [])
        status.update(
            {
                "persisted_count": len(item_ids),
                "quality_passed": report.passed,
                "event_types": [event.event_type for event in events],
            }
        )
        return {
            "question_items": [item.model_dump(mode="json") for item in items],
            "question_item_ids": item_ids,
            "learning_events": [*existing_events, *[event.model_dump(mode="json") for event in events]],
            "generation_status": status,
            "errors": errors,
        }

    return persist_question_items_node


def compose_response_node(state: QuestionGenerationState) -> dict[str, Any]:
    report = QualityReport.model_validate(state.get("quality_report") or {})
    item_ids = list(state.get("question_item_ids") or [])
    blueprint = ItemBlueprint.model_validate(state.get("generation_blueprint") or {})
    source_refs = list(state.get("source_refs") or [])
    status = dict(state.get("generation_status") or {})
    quality_failure_summary = "" if report.passed else _quality_failure_summary(report, status)
    if report.passed:
        if status.get("persist_degraded"):
            answer = f"已围绕「{blueprint.concept_name}」生成 {len(item_ids)} 道{blueprint.difficulty}单选题，已放入本轮练习；长期题库保存稍后会再试。"
        else:
            answer = f"已围绕「{blueprint.concept_name}」生成并保存 {len(item_ids)} 道{blueprint.difficulty}单选题。"
    else:
        answer = f"围绕「{blueprint.concept_name}」的出题未通过质量门，本轮没有保存题目。"
        if quality_failure_summary:
            answer += f"原因：{quality_failure_summary}"

    response = FinalResponse(
        answer=answer,
        source_level=_source_level(source_refs),
        concepts=[
            ConceptRef(
                concept_id=blueprint.primary_concept_id,
                name=blueprint.concept_name,
                confidence=0.8,
                source="question_generation_blueprint",
            )
        ],
        evidence_refs=[str(ref.get("evidence_id")) for ref in source_refs if ref.get("evidence_id")],
        coach_actions=["practice_question_generated" if report.passed else "revise_question_blueprint"],
        ui_payload={
            "target_graph_type": GraphType.QUESTION_GENERATION.value,
            "question_item_ids": item_ids,
            "quality_passed": report.passed,
            "quality_report": report.model_dump(mode="json"),
            "quality_failure_summary": quality_failure_summary,
            "quiz_generation_status": status,
            "errors": list(state.get("errors") or []),
        },
    )
    return {"final_response": response.model_dump(mode="json")}


def _primary_concept(state: QuestionGenerationState) -> ConceptRef:
    quiz_request = state.get("quiz_request") if isinstance(state.get("quiz_request"), dict) else {}
    quiz_topic = str(
        quiz_request.get("active_topic") or quiz_request.get("requested_topic") or quiz_request.get("topic") or ""
    ).strip()
    canonical_subject_topic = _canonical_subject_topic(
        str(quiz_request.get("subject_id") or state.get("subject_id") or state.get("notebook_id") or "")
    )
    if canonical_subject_topic and _is_generic_topic_name(quiz_topic):
        quiz_topic = canonical_subject_topic
    if quiz_topic:
        return ConceptRef(
            concept_id=_stable_concept_id(quiz_topic),
            name=quiz_topic,
            confidence=0.9,
            source=str(quiz_request.get("source") or "quiz_request"),
        )

    raw_concepts = list(state.get("concepts") or [])
    if raw_concepts:
        first = raw_concepts[0]
        if isinstance(first, dict):
            name = str(first.get("name") or first.get("concept_name") or first.get("concept_id") or "").strip()
            concept_id = str(first.get("concept_id") or "").strip() or _stable_concept_id(name)
            return ConceptRef(concept_id=concept_id, name=name or "综合练习", confidence=0.8, source="state")
        text = str(first).strip()
        return ConceptRef(concept_id=_stable_concept_id(text), name=text or "综合练习", confidence=0.7, source="state")

    event_concept = _concept_from_learning_events(state)
    if event_concept is not None:
        return event_concept

    message = str(state.get("user_message") or "").strip()
    topic = message
    for token in ("帮我出题练习", "给我出题", "出题练习", "练习", "帮我"):
        topic = topic.replace(token, "")
    topic = topic.strip(" ：:，,。.!！?？") or "综合练习"
    return ConceptRef(concept_id=_stable_concept_id(topic), name=topic, confidence=0.6, source="user_message")


def _concept_from_learning_events(state: QuestionGenerationState) -> ConceptRef | None:
    for raw_event in list(state.get("learning_events") or []):
        if hasattr(raw_event, "model_dump"):
            raw_event = raw_event.model_dump(mode="json")
        if not isinstance(raw_event, dict):
            continue
        payload = raw_event.get("payload") if isinstance(raw_event.get("payload"), dict) else {}
        event_type = str(raw_event.get("event_type") or "")
        if event_type not in {
            LearningEventType.QUESTION_ANSWERED.value,
            LearningEventType.CONCEPT_EXPLAINED.value,
            LearningEventType.EVIDENCE_USED.value,
            LearningEventType.TOOL_FALLBACK_USED.value,
            LearningEventType.INSUFFICIENT_EVIDENCE.value,
            LearningEventType.ANSWER_REPAIRED.value,
        }:
            continue
        concept_id = str(
            raw_event.get("concept_id")
            or payload.get("concept_id")
            or payload.get("concept")
            or payload.get("topic")
            or ""
        ).strip()
        name = str(
            payload.get("concept_name")
            or payload.get("name")
            or payload.get("knowledge_point")
            or payload.get("topic")
            or payload.get("concept")
            or concept_id
        ).strip()
        if concept_id or name:
            return ConceptRef(
                concept_id=concept_id or _stable_concept_id(name),
                name=name or concept_id,
                confidence=0.65,
                source="learning_event",
            )
    return None


def _canonical_subject_topic(subject_id: str) -> str:
    return {
        "data-structure": "数据结构与算法",
        "computer-network": "计算机网络",
        "computer-organization": "计算机组成原理",
        "operating-system": "操作系统原理",
    }.get(str(subject_id or "").strip(), "")


def _is_generic_topic_name(topic: str) -> bool:
    compact = str(topic or "").replace(" ", "").strip("：:，,。.!！?？的")
    return compact in {
        "",
        "有关",
        "有关的",
        "相关",
        "相关的",
        "类型",
        "方向",
        "方面",
        "知识库",
        "学科",
        "课程",
        "题",
        "题目",
        "练习",
    }


def _topic_alignment_issue(
    blueprint: ItemBlueprint,
    candidate: QuestionCandidate,
    index: int,
) -> str:
    topic = blueprint.concept_name.strip()
    if not topic:
        return ""

    text = _candidate_search_text(candidate)
    normalized_text = _normalize_for_topic_match(text)
    normalized_topic = _normalize_for_topic_match(topic)
    subject_id = str(blueprint.constraints.get("subject_id") or "")

    profile = _topic_profile(topic, subject_id)
    if profile:
        blocked = [term for term in profile["blocked"] if term in normalized_text]
        matched = [term for term in profile["keywords"] if term in normalized_text]
        if blocked:
            return f"第 {index} 题主题不一致: requested={topic}, detected={','.join(blocked[:3])}"
        if not matched:
            return f"第 {index} 题主题不一致: 未体现「{topic}」相关知识点"
        return ""

    if normalized_topic and normalized_topic in normalized_text:
        return ""

    aliases = _topic_aliases(topic)
    if any(_normalize_for_topic_match(alias) in normalized_text for alias in aliases if alias):
        return ""

    return f"第 {index} 题主题不一致: 未体现「{topic}」"


def _candidate_search_text(candidate: QuestionCandidate) -> str:
    parts = [
        candidate.stem,
        candidate.primary_concept_id,
        candidate.answer_key.correct_option_text,
        candidate.answer_key.explanation,
        candidate.rubric.full_credit,
        " ".join(candidate.rubric.criteria),
        " ".join(candidate.rubric.common_misconceptions),
    ]
    parts.extend(option.text for option in candidate.options)
    parts.extend(candidate.answer_key.option_rationales.values())
    return " ".join(parts)


def _normalize_for_topic_match(value: str) -> str:
    return str(value or "").replace(" ", "").replace("　", "").lower()


def _topic_profile(topic: str, subject_id: str) -> dict[str, tuple[str, ...]] | None:
    compact = _normalize_for_topic_match(topic)
    if subject_id == "data-structure" or any(term in compact for term in ("数据结构", "数据与结构", "算法")):
        return {
            "keywords": (
                "数据结构",
                "算法",
                "数组",
                "链表",
                "栈",
                "队列",
                "树",
                "二叉树",
                "图",
                "哈希",
                "hash",
                "排序",
                "查找",
                "复杂度",
                "堆",
            ),
            "blocked": (
                "http",
                "https",
                "tcp",
                "udp",
                "dns",
                "ip协议",
                "状态码",
                "请求",
                "响应",
                "端口",
                "三次握手",
                "浏览器",
                "服务器",
            ),
        }
    if subject_id == "computer-network" or any(term in compact for term in ("计算机网络", "网络原理", "计网")):
        return {
            "keywords": (
                "网络",
                "协议",
                "tcp",
                "udp",
                "http",
                "dns",
                "ip",
                "路由",
                "交换",
                "端口",
                "拥塞",
                "握手",
            ),
            "blocked": ("二叉树", "链表", "数组", "排序", "哈希表", "进程调度", "寄存器"),
        }
    if subject_id == "computer-organization" or any(term in compact for term in ("计算机组成", "组成原理", "计组")):
        return {
            "keywords": ("cpu", "寄存器", "指令", "流水线", "缓存", "总线", "存储器", "alu", "补码"),
            "blocked": ("http", "tcp", "二叉树", "链表", "进程调度"),
        }
    if subject_id == "operating-system" or any(term in compact for term in ("操作系统", "os")):
        return {
            "keywords": ("进程", "线程", "调度", "死锁", "内存管理", "虚拟内存", "文件系统", "系统调用", "同步"),
            "blocked": ("http", "tcp", "二叉树", "链表", "寄存器"),
        }
    return None


def _topic_aliases(topic: str) -> tuple[str, ...]:
    compact = _normalize_for_topic_match(topic)
    if "hashmap" in compact or "hash map" in topic.lower() or "哈希" in compact:
        return ("HashMap", "哈希", "散列", "哈希表")
    if "http" in compact:
        return ("HTTP", "请求", "响应", "状态码", "浏览器", "服务器")
    if "tcp" in compact:
        return ("TCP", "三次握手", "可靠传输", "拥塞控制", "传输层")
    return (topic,)


def _stable_concept_id(name: str) -> str:
    normalized = name.strip().lower().replace(" ", "-")
    return normalized[:64] or "general"


def _bounded_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 1
    return max(1, min(10, count))


def _difficulty_label(value: str) -> str:
    return {
        "easy": "基础",
        "medium": "变式",
        "hard": "易错",
        "adaptive": "基础",
        "unknown": "基础",
    }.get(value, value or "基础")


def _bounded_retry_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 2
    return max(1, min(3, count))


def _candidate_list(state: QuestionGenerationState) -> list[QuestionCandidate]:
    return [QuestionCandidate.model_validate(item) for item in list(state.get("question_candidates") or [])]


def _grounded_in_notebook(candidate: QuestionCandidate) -> bool:
    return any(ref.source_type in {"notebook", "course", "question_bank"} for ref in candidate.source_refs)


def _blueprint_concept_id(state: QuestionGenerationState) -> str:
    blueprint = ItemBlueprint.model_validate(state.get("generation_blueprint") or {})
    return blueprint.primary_concept_id


def _learning_event(
    state: QuestionGenerationState,
    *,
    event_type: str,
    concept_id: str,
    payload: dict[str, Any],
) -> LearningEvent:
    if event_type not in ALLOWED_QGEN_EVENTS:
        raise ValueError(f"Unsupported QuestionGenerationGraph event_type: {event_type}")
    return LearningEvent(
        id=new_event_id(),
        event_type=event_type,
        user_id=str(state.get("user_id") or ""),
        concept_id=concept_id,
        graph_run_id=str(state.get("run_id") or state.get("graph_run_id") or ""),
        payload=payload,
    )


def _source_level(source_refs: list[dict[str, Any]]) -> SourceLevel:
    source_types = {str(ref.get("source_type") or "") for ref in source_refs}
    if not source_types or source_types == {"generator"}:
        return SourceLevel.MODEL
    if source_types <= {"notebook", "course", "question_bank"}:
        return SourceLevel.NOTEBOOK
    if source_types <= {"web"}:
        return SourceLevel.WEB
    return SourceLevel.MIXED


def _is_degraded_generation(status: dict[str, Any]) -> bool:
    return bool(
        status.get("source_refs_degraded")
        or status.get("partial")
        or status.get("degraded_reason")
        or status.get("question_bank_unavailable")
        or status.get("ai_generation_failed")
        or int(status.get("fallback_count") or 0) > 0
    )


def _degraded_reason(status: dict[str, Any]) -> str:
    reason = str(status.get("degraded_reason") or "").strip()
    if reason:
        return reason
    if status.get("source_refs_degraded"):
        return "no_evidence_source_refs"
    if status.get("question_bank_unavailable"):
        return "question_bank_unavailable"
    if status.get("ai_generation_failed"):
        return "ai_generation_failed"
    if status.get("partial"):
        return "partial_generation"
    if int(status.get("fallback_count") or 0) > 0:
        return "fallback_questions_used"
    return "question_generation_degraded"


def _quality_failure_summary(report: QualityReport, status: dict[str, Any]) -> str:
    if report.issues:
        primary_issue = str(report.issues[0]).strip()
        if primary_issue:
            return primary_issue
    if status.get("empty_generation"):
        return "没有生成足够题目。"
    degraded_reason = str(status.get("degraded_reason") or "").strip()
    if degraded_reason:
        return degraded_reason
    return "题目结构或主题对齐检查未通过。"
