from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.orchestration.graphs.question_generation.adapter import (
    EmptyQuestionCandidateGenerator,
    LegacyPracticeQuestionCandidateGenerator,
)
from app.orchestration.graphs.question_generation.graph import build_graph
from app.orchestration.graphs.question_generation.schemas import (
    AnswerKey,
    ItemBlueprint,
    QualityReport,
    QuestionCandidate,
    QuestionItem,
    Rubric,
    SourceRef,
)
from app.orchestration.graphs.shared.schemas import (
    FinalResponse,
    GraphType,
    LearningEvent,
    LearningEventType,
    SourcePolicy,
)
from app.persistence.repositories.question_items import LegacyQuestionBankItemRepository
from app.shared.schemas.contracts import PracticeRecommendation, QuestionBankItemRecord


class MockQuestionItemRepository:
    def __init__(self, similar: list[dict[str, Any]] | None = None) -> None:
        self.created: list[dict[str, Any]] = []
        self.similar = similar or []

    def create_question_item(self, payload: dict[str, Any]) -> str:
        item_id = f"mock-q-{len(self.created) + 1}"
        self.created.append({**payload, "id": item_id})
        return item_id

    def find_similar(self, payload: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
        return self.similar[:limit]


class MockLearningEventRepository:
    def __init__(self) -> None:
        self.events: list[LearningEvent] = []

    def append(self, event: LearningEvent) -> str:
        self.events.append(event)
        return event.id

    def list_for_user(self, *, user_id: str, limit: int = 100) -> list[LearningEvent]:
        return [event for event in self.events if event.user_id == user_id][:limit]


class QuestionGenerationGraphAdapterTest(unittest.TestCase):
    def test_schema_contracts_are_serializable_and_complete(self) -> None:
        source_ref = SourceRef(source_type="notebook", source_id="chunk-1", evidence_id="e1")
        candidate = QuestionCandidate(
            stem="HTTP 协议的默认端口号是哪个？",
            options=[
                {"key": "A", "text": "21"},
                {"key": "B", "text": "53"},
                {"key": "C", "text": "80"},
                {"key": "D", "text": "443"},
            ],
            primary_concept_id="http-port",
            source_refs=[source_ref],
            answer_key=AnswerKey(
                correct_option="C",
                correct_option_text="80",
                explanation="HTTP 的默认端口是 80，HTTPS 的默认端口才是 443。",
                option_rationales={
                    "A": "21 通常用于 FTP。",
                    "B": "53 通常用于 DNS。",
                    "C": "80 是 HTTP 默认端口。",
                    "D": "443 是 HTTPS 默认端口。",
                },
            ),
            rubric=Rubric(
                criteria=["single_correct_option"],
                full_credit="选择 C 并说明 HTTP 默认端口是 80。",
            ),
        )
        item = QuestionItem(
            id="q1",
            stem=candidate.stem,
            options=candidate.options,
            primary_concept_id=candidate.primary_concept_id,
            source_refs=candidate.source_refs,
            answer_key=candidate.answer_key,
            rubric=candidate.rubric,
            quality_report=QualityReport(passed=True),
        )

        payload = {
            "blueprint": ItemBlueprint(primary_concept_id="http-port", concept_name="HTTP 默认端口").model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "item": item.model_dump(mode="json"),
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertIn("source_refs", encoded)
        self.assertIn("answer_key", encoded)
        self.assertIn("rubric", encoded)

    def test_graph_compiles_generates_persists_and_emits_learning_events(self) -> None:
        question_repo = MockQuestionItemRepository()
        event_repo = MockLearningEventRepository()
        result = build_graph(
            question_item_repository=question_repo,
            learning_event_repository=event_repo,
        ).compile().invoke(
            {
                "run_id": "run-qgen-1",
                "user_id": "u1",
                "user_message": "帮我出题练习 HTTP 默认端口",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                "difficulty": "基础",
                "count": 1,
                "concepts": [{"concept_id": "http-port", "name": "HTTP 默认端口"}],
                "evidence": [
                    {
                        "id": "e1",
                        "source_type": "notebook",
                        "source_id": "chunk-1",
                        "text": "HTTP 默认端口是 80，HTTPS 默认端口是 443。",
                    }
                ],
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        self.assertTrue(response.ui_payload["quality_passed"])
        self.assertEqual(result["question_item_ids"], ["mock-q-1"])
        self.assertEqual(len(question_repo.created), 1)
        saved = QuestionItem.model_validate(question_repo.created[0])
        self.assertEqual(saved.primary_concept_id, "http-port")
        self.assertEqual(saved.source_refs[0].evidence_id, "e1")
        self.assertTrue(saved.answer_key.correct_option_text)
        self.assertTrue(saved.rubric.full_credit)

        event_types = [event.event_type for event in event_repo.events]
        self.assertEqual(event_types, ["question_reviewed", "question_generated"])
        self.assertEqual(event_repo.events[1].payload["question_item_id"], "mock-q-1")
        self.assertEqual(event_repo.events[1].payload["source_refs"][0]["evidence_id"], "e1")
        json.dumps(result, ensure_ascii=False)

    def test_quality_gate_blocks_notebook_only_without_notebook_source(self) -> None:
        question_repo = MockQuestionItemRepository()
        event_repo = MockLearningEventRepository()
        result = build_graph(
            question_item_repository=question_repo,
            learning_event_repository=event_repo,
        ).compile().invoke(
            {
                "run_id": "run-qgen-2",
                "user_id": "u1",
                "user_message": "帮我出题练习 HTTP 默认端口",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                "count": 1,
            }
        )

        report = QualityReport.model_validate(result["quality_report"])
        self.assertFalse(report.passed)
        self.assertTrue(any("notebook_only grounding" in issue for issue in report.issues))
        self.assertEqual(question_repo.created, [])
        self.assertEqual([event.event_type for event in event_repo.events], ["question_reviewed", "question_generation_failed"])

    def test_dedupe_checker_blocks_persisting_duplicate_items(self) -> None:
        question_repo = MockQuestionItemRepository(similar=[{"id": "existing-q-1"}])
        result = build_graph(question_item_repository=question_repo).compile().invoke(
            {
                "run_id": "run-qgen-3",
                "user_id": "u1",
                "user_message": "帮我出题练习 HTTP 默认端口",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "count": 1,
            }
        )

        report = QualityReport.model_validate(result["quality_report"])
        self.assertFalse(report.passed)
        self.assertEqual(report.dedupe_checker.duplicate_question_ids, ["existing-q-1"])
        self.assertEqual(question_repo.created, [])

    def test_question_generation_graph_does_not_write_mastery_or_attempts(self) -> None:
        graph_root = REPO_ROOT / "backend" / "app" / "orchestration" / "graphs" / "question_generation"
        forbidden = {
            "MasterySnapshotRepository",
            "upsert_snapshot",
            "record_attempt",
            "record_exposure",
            "user_knowledge_stats",
            "TavilyClient",
            "tavily_web_search",
        }
        for path in sorted(graph_root.glob("*.py")):
            content = path.read_text(encoding="utf-8")
            leaked = {symbol for symbol in forbidden if symbol in content}
            self.assertFalse(leaked, f"{path} leaked forbidden boundary symbols: {leaked}")

    def test_legacy_practice_generator_maps_practice_recommendation_to_candidate(self) -> None:
        class FakeGenerationResult:
            items = [
                PracticeRecommendation(
                    question_id="legacy-q1",
                    question="HTTP 的默认端口是什么？",
                    options=[
                        {"key": "A", "text": "21"},
                        {"key": "B", "text": "53"},
                        {"key": "C", "text": "80"},
                        {"key": "D", "text": "443"},
                    ],
                    correct_option="C",
                    explanation="HTTP 的默认端口是 80。",
                    option_rationales={
                        "A": "21 通常用于 FTP。",
                        "B": "53 通常用于 DNS。",
                        "C": "80 是 HTTP 默认端口。",
                        "D": "443 是 HTTPS 默认端口。",
                    },
                    knowledge_point="HTTP 默认端口",
                    difficulty="基础",
                    source_type="ai_generated",
                )
            ]

        blueprint = ItemBlueprint(primary_concept_id="http-port", concept_name="HTTP 默认端口")
        with patch(
            "app.orchestration.graphs.question_generation.adapter.build_mixed_practice_items_with_status",
            return_value=FakeGenerationResult(),
        ):
            candidates = LegacyPracticeQuestionCandidateGenerator(
                user_id="u1",
                subject_id="network",
                subject_name="网络",
                original_question="帮我出题",
            ).generate(
                blueprint=blueprint,
                source_refs=[SourceRef(source_type="notebook", source_id="chunk-1", evidence_id="e1")],
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].primary_concept_id, "http-port")
        self.assertEqual(candidates[0].answer_key.correct_option, "C")
        self.assertEqual(candidates[0].source_refs[0].evidence_id, "e1")

    def test_generates_from_learning_event_concept_when_concept_refs_are_absent(self) -> None:
        question_repo = MockQuestionItemRepository()
        event_repo = MockLearningEventRepository()
        result = build_graph(
            question_item_repository=question_repo,
            learning_event_repository=event_repo,
        ).compile().invoke(
            {
                "run_id": "run-qgen-event-concept",
                "user_id": "u1",
                "user_message": "帮我出题",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "learning_events": [
                    LearningEvent(
                        event_type=LearningEventType.CONCEPT_EXPLAINED.value,
                        user_id="u1",
                        concept_id="http-cache",
                        graph_run_id="run-qa",
                        payload={"concept_name": "HTTP 缓存"},
                    ).model_dump(mode="json")
                ],
            }
        )

        saved = QuestionItem.model_validate(question_repo.created[0])
        response = FinalResponse.model_validate(result["final_response"])
        self.assertEqual(saved.primary_concept_id, "http-cache")
        self.assertEqual(response.concepts[0].name, "HTTP 缓存")

    def test_no_evidence_open_tools_degrades_to_generator_source_without_failing(self) -> None:
        question_repo = MockQuestionItemRepository()
        event_repo = MockLearningEventRepository()
        result = build_graph(
            question_item_repository=question_repo,
            learning_event_repository=event_repo,
        ).compile().invoke(
            {
                "run_id": "run-qgen-no-evidence",
                "user_id": "u1",
                "user_message": "帮我出题练习 HTTP",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "concepts": [{"concept_id": "http", "name": "HTTP"}],
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        self.assertTrue(response.ui_payload["quality_passed"])
        self.assertEqual(response.source_level.value, "model")
        self.assertEqual(result["generation_status"]["source_ref_policy"], "generator_fallback")
        event_types = [event.event_type for event in event_repo.events]
        self.assertIn(LearningEventType.QUESTION_GENERATION_DEGRADED.value, event_types)
        self.assertIn(LearningEventType.QUESTION_GENERATED.value, event_types)
        degraded = next(
            event
            for event in event_repo.events
            if event.event_type == LearningEventType.QUESTION_GENERATION_DEGRADED.value
        )
        self.assertEqual(degraded.payload["reason"], "no_evidence_source_refs")

    def test_data_structure_subject_fallback_generates_specific_non_network_questions(self) -> None:
        question_repo = MockQuestionItemRepository()
        result = build_graph(question_item_repository=question_repo).compile().invoke(
            {
                "run_id": "run-qgen-data-structure",
                "user_id": "u1",
                "user_message": "出一些数据与结构类型的题目给我",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "quiz_request": {
                    "is_quiz_request": True,
                    "action": "generate_practice_pack",
                    "intent": "quiz_generation",
                    "topic": "数据结构与算法",
                    "subject_id": "data-structure",
                    "source": "explicit_user_input",
                    "question_type": "single_choice",
                    "difficulty": "easy",
                    "count": 5,
                    "target_module": "practice",
                    "reason": "explicit_topic_in_user_input",
                },
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        stems = [str(item["stem"]) for item in question_repo.created]
        joined = "\n".join(stems)
        self.assertTrue(response.ui_payload["quality_passed"])
        self.assertEqual(len(stems), 5)
        self.assertEqual(len(set(stems)), 5)
        self.assertNotIn("TCP", joined)
        self.assertNotIn("UDP", joined)
        self.assertFalse(any("学习方法" in stem for stem in stems))
        self.assertTrue(any("数组" in stem or "链表" in stem for stem in stems))

    def test_topic_alignment_retries_once_and_repairs_mismatched_http_questions(self) -> None:
        class MismatchedThenAlignedGenerator:
            def __init__(self) -> None:
                self.calls = 0

            def generate_with_status(self, *, blueprint: ItemBlueprint, source_refs: list[SourceRef]):
                self.calls += 1
                if self.calls == 1:
                    stem = "HTTP 协议的默认端口号是哪个？"
                    options = [
                        {"key": "A", "text": "21"},
                        {"key": "B", "text": "53"},
                        {"key": "C", "text": "80"},
                        {"key": "D", "text": "443"},
                    ]
                    correct = "C"
                    explanation = "HTTP 的默认端口是 80，HTTPS 的默认端口才是 443。"
                    rationales = {
                        "A": "21 通常用于 FTP。",
                        "B": "53 通常用于 DNS。",
                        "C": "80 是 HTTP 默认端口。",
                        "D": "443 是 HTTPS 默认端口。",
                    }
                else:
                    stem = "栈这种数据结构最典型的访问规则是什么？"
                    options = [
                        {"key": "A", "text": "先进先出"},
                        {"key": "B", "text": "后进先出"},
                        {"key": "C", "text": "按优先级先出"},
                        {"key": "D", "text": "随机访问任意位置"},
                    ]
                    correct = "B"
                    explanation = "栈的核心规则是 LIFO：后进入栈的元素先被弹出。"
                    rationales = {
                        "A": "先进先出是队列。",
                        "B": "后进先出是栈。",
                        "C": "这是优先队列。",
                        "D": "这不是栈的核心模型。",
                    }

                candidate = QuestionCandidate(
                    stem=stem,
                    options=options,
                    primary_concept_id=blueprint.primary_concept_id,
                    difficulty=blueprint.difficulty,
                    source_refs=source_refs,
                    answer_key=AnswerKey(
                        correct_option=correct,
                        correct_option_text=next(item["text"] for item in options if item["key"] == correct),
                        explanation=explanation,
                        option_rationales=rationales,
                    ),
                    rubric=Rubric(criteria=["唯一正确答案"], full_credit=f"选择 {correct} 并说明：{explanation}"),
                    generation_source="mismatch_then_aligned",
                )
                return type(
                    "Result",
                    (),
                    {
                        "candidates": [candidate],
                        "status": {"generation_source": "mismatch_then_aligned", "generated_count": 1},
                    },
                )()

        generator = MismatchedThenAlignedGenerator()
        question_repo = MockQuestionItemRepository()
        result = build_graph(
            candidate_generator=generator,
            question_item_repository=question_repo,
        ).compile().invoke(
            {
                "run_id": "run-qgen-topic-repair",
                "user_id": "u1",
                "user_message": "生成一些有关数据结构的题目",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "quiz_request": {
                    "is_quiz_request": True,
                    "action": "generate_practice_pack",
                    "intent": "quiz_generation",
                    "topic": "数据结构与算法",
                    "requested_topic": "数据结构与算法",
                    "previous_topic": "HTTP",
                    "active_topic": "数据结构与算法",
                    "should_switch_topic": True,
                    "subject_id": "data-structure",
                    "source": "explicit_user_input",
                    "question_type": "single_choice",
                    "difficulty": "easy",
                    "count": 1,
                    "target_module": "practice",
                    "reason": "explicit_topic_in_user_input",
                },
            }
        )

        report = QualityReport.model_validate(result["quality_report"])
        self.assertEqual(generator.calls, 2)
        self.assertTrue(report.passed)
        self.assertEqual(result["generation_status"]["quality_retry_count"], 1)
        self.assertEqual(len(question_repo.created), 1)
        self.assertIn("栈", question_repo.created[0]["stem"])

    def test_topic_alignment_blocks_mismatched_http_questions_after_retry_limit(self) -> None:
        class AlwaysHttpGenerator:
            def __init__(self) -> None:
                self.calls = 0

            def generate_with_status(self, *, blueprint: ItemBlueprint, source_refs: list[SourceRef]):
                self.calls += 1
                candidate = QuestionCandidate(
                    stem="HTTP 协议的默认端口号是哪个？",
                    options=[
                        {"key": "A", "text": "21"},
                        {"key": "B", "text": "53"},
                        {"key": "C", "text": "80"},
                        {"key": "D", "text": "443"},
                    ],
                    primary_concept_id=blueprint.primary_concept_id,
                    difficulty=blueprint.difficulty,
                    source_refs=source_refs,
                    answer_key=AnswerKey(
                        correct_option="C",
                        correct_option_text="80",
                        explanation="HTTP 的默认端口是 80。",
                        option_rationales={
                            "A": "21 通常用于 FTP。",
                            "B": "53 通常用于 DNS。",
                            "C": "80 是 HTTP 默认端口。",
                            "D": "443 是 HTTPS 默认端口。",
                        },
                    ),
                    rubric=Rubric(criteria=["唯一正确答案"], full_credit="选择 C 并说明 HTTP 默认端口。"),
                    generation_source="always_http",
                )
                return type(
                    "Result",
                    (),
                    {"candidates": [candidate], "status": {"generation_source": "always_http", "generated_count": 1}},
                )()

        generator = AlwaysHttpGenerator()
        question_repo = MockQuestionItemRepository()
        result = build_graph(
            candidate_generator=generator,
            question_item_repository=question_repo,
        ).compile().invoke(
            {
                "run_id": "run-qgen-topic-block",
                "user_id": "u1",
                "user_message": "生成一些有关数据结构的题目",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "quiz_request": {
                    "is_quiz_request": True,
                    "action": "generate_practice_pack",
                    "intent": "quiz_generation",
                    "topic": "数据结构与算法",
                    "requested_topic": "数据结构与算法",
                    "active_topic": "数据结构与算法",
                    "subject_id": "data-structure",
                    "source": "explicit_user_input",
                    "question_type": "single_choice",
                    "difficulty": "easy",
                    "count": 1,
                    "target_module": "practice",
                    "reason": "explicit_topic_in_user_input",
                },
            }
        )

        report = QualityReport.model_validate(result["quality_report"])
        self.assertFalse(report.passed)
        self.assertEqual(generator.calls, 2)
        self.assertEqual(question_repo.created, [])
        self.assertTrue(any("主题不一致" in issue for issue in report.issues))

    def test_subject_id_falls_back_when_topic_is_generic_noise(self) -> None:
        question_repo = MockQuestionItemRepository()
        result = build_graph(question_item_repository=question_repo).compile().invoke(
            {
                "run_id": "run-qgen-generic-topic",
                "user_id": "u1",
                "user_message": "帮我出一些有关数据与结构有关的题目",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "quiz_request": {
                    "is_quiz_request": True,
                    "action": "generate_practice_pack",
                    "intent": "quiz_generation",
                    "topic": "有关的",
                    "requested_topic": "有关的",
                    "active_topic": "有关的",
                    "subject_id": "data-structure",
                    "source": "explicit_user_input",
                    "question_type": "single_choice",
                    "difficulty": "easy",
                    "count": 5,
                    "target_module": "practice",
                    "reason": "explicit_topic_in_user_input",
                },
            }
        )

        response = FinalResponse.model_validate(result["final_response"])
        stems = "\n".join(str(item["stem"]) for item in question_repo.created)
        self.assertTrue(response.ui_payload["quality_passed"])
        self.assertIn("数据结构与算法", response.answer)
        self.assertEqual(len(question_repo.created), 5)
        self.assertIn("数组", stems)
        self.assertNotIn("HTTP", stems)

    def test_empty_generation_records_graph_error_and_does_not_persist_question_item(self) -> None:
        question_repo = MockQuestionItemRepository()
        event_repo = MockLearningEventRepository()
        result = build_graph(
            candidate_generator=EmptyQuestionCandidateGenerator(),
            question_item_repository=question_repo,
            learning_event_repository=event_repo,
        ).compile().invoke(
            {
                "run_id": "run-qgen-empty",
                "user_id": "u1",
                "user_message": "帮我出题练习 HTTP",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "concepts": [{"concept_id": "http", "name": "HTTP"}],
            }
        )

        report = QualityReport.model_validate(result["quality_report"])
        response = FinalResponse.model_validate(result["final_response"])
        self.assertFalse(report.passed)
        self.assertEqual(question_repo.created, [])
        self.assertEqual(result["errors"][0]["code"], "question_generation_empty")
        self.assertIn("question_generation_empty", json.dumps(response.ui_payload["errors"], ensure_ascii=False))
        self.assertEqual(
            [event.event_type for event in event_repo.events],
            [
                LearningEventType.QUESTION_REVIEWED.value,
                LearningEventType.QUESTION_GENERATION_FAILED.value,
            ],
        )

    def test_candidate_generation_retries_once_before_quality_gate(self) -> None:
        class FlakyGenerator:
            def __init__(self) -> None:
                self.calls = 0

            def generate_with_status(self, *, blueprint: ItemBlueprint, source_refs: list[SourceRef]):
                self.calls += 1
                if self.calls == 1:
                    return type("Result", (), {"candidates": [], "status": {"generation_source": "flaky"}})()
                candidate = QuestionCandidate(
                    stem="HTTP 协议的默认端口号是哪个？",
                    options=[
                        {"key": "A", "text": "21"},
                        {"key": "B", "text": "53"},
                        {"key": "C", "text": "80"},
                        {"key": "D", "text": "443"},
                    ],
                    primary_concept_id=blueprint.primary_concept_id,
                    difficulty=blueprint.difficulty,
                    source_refs=source_refs,
                    answer_key=AnswerKey(
                        correct_option="C",
                        correct_option_text="80",
                        explanation="HTTP 的默认端口是 80。",
                        option_rationales={
                            "A": "21 通常用于 FTP。",
                            "B": "53 通常用于 DNS。",
                            "C": "80 是 HTTP 默认端口。",
                            "D": "443 是 HTTPS 默认端口。",
                        },
                    ),
                    rubric=Rubric(criteria=["唯一正确答案"], full_credit="选择 C 并说明 HTTP 默认端口。"),
                    generation_source="flaky",
                )
                return type(
                    "Result",
                    (),
                    {"candidates": [candidate], "status": {"generation_source": "flaky", "retry_count": 1}},
                )()

        generator = FlakyGenerator()
        result = build_graph(
            candidate_generator=generator,
            question_item_repository=MockQuestionItemRepository(),
        ).compile().invoke(
            {
                "run_id": "run-qgen-retry",
                "user_id": "u1",
                "user_message": "帮我出题练习 HTTP",
                "graph_type": GraphType.QUESTION_GENERATION.value,
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "concepts": [{"concept_id": "http", "name": "HTTP"}],
            }
        )

        report = QualityReport.model_validate(result["quality_report"])
        self.assertEqual(generator.calls, 2)
        self.assertTrue(report.passed)
        self.assertEqual(result["generation_status"]["retry_count"], 1)

    def test_legacy_practice_generator_preserves_status_for_graph_mapping(self) -> None:
        class FakeGenerationResult:
            items = [
                PracticeRecommendation(
                    question_id="legacy-q2",
                    question="HTTPS 与 HTTP 的默认端口对应关系，哪一项正确？",
                    options=[
                        {"key": "A", "text": "HTTP 80，HTTPS 443"},
                        {"key": "B", "text": "HTTP 443，HTTPS 80"},
                        {"key": "C", "text": "HTTP 53，HTTPS 21"},
                        {"key": "D", "text": "HTTP 22，HTTPS 25"},
                    ],
                    correct_option="A",
                    explanation="HTTP 默认端口是 80，HTTPS 默认端口是 443。",
                    option_rationales={
                        "A": "这组端口对应关系正确。",
                        "B": "把 HTTP 和 HTTPS 的默认端口写反了。",
                        "C": "53 常用于 DNS，21 常用于 FTP。",
                        "D": "22 常用于 SSH，25 常用于 SMTP。",
                    },
                    knowledge_point="HTTP 默认端口",
                    difficulty="基础",
                    source_type="ai_generated",
                )
            ]
            status = {
                "requested_count": 1,
                "generated_count": 1,
                "question_bank_count": 0,
                "ai_count": 0,
                "fallback_count": 1,
                "partial": False,
                "degraded_reason": "AI 选择题不足，已用备用题补齐。",
            }

        generator = LegacyPracticeQuestionCandidateGenerator(subject_id="network", subject_name="网络")
        with patch(
            "app.orchestration.graphs.question_generation.adapter.build_mixed_practice_items_with_status",
            return_value=FakeGenerationResult(),
        ):
            result = generator.generate_with_status(
                blueprint=ItemBlueprint(primary_concept_id="http-port", concept_name="HTTP 默认端口"),
                source_refs=[SourceRef(source_type="notebook", source_id="chunk-1", evidence_id="e1")],
            )

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.status["generation_source"], "practice_generation")
        self.assertEqual(result.status["fallback_count"], 1)
        self.assertTrue(result.status["production_output_mapped"])

    def test_legacy_question_bank_repository_maps_question_item_through_protocol_boundary(self) -> None:
        saved_payloads: list[list[dict[str, Any]]] = []

        def fake_upsert(items: list[dict[str, Any]]) -> int:
            saved_payloads.append(items)
            return len(items)

        def fake_list(**kwargs: Any) -> list[QuestionBankItemRecord]:
            return [
                QuestionBankItemRecord(
                    id="existing-q1",
                    question_id="existing-q1",
                    subject_id="network",
                    knowledge_point="http",
                    question="HTTP 协议的默认端口号是哪个？",
                    options=[
                        {"key": "A", "text": "21"},
                        {"key": "B", "text": "53"},
                        {"key": "C", "text": "80"},
                        {"key": "D", "text": "443"},
                    ],
                    correct_option="C",
                    explanation="HTTP 的默认端口是 80。",
                    option_rationales={},
                    difficulty="基础",
                )
            ]

        repo = LegacyQuestionBankItemRepository(subject_id="network")
        payload = {
            "id": "qgen-q1",
            "stem": "HTTP 协议的默认端口号是哪个？",
            "options": [
                {"key": "A", "text": "21"},
                {"key": "B", "text": "53"},
                {"key": "C", "text": "80"},
                {"key": "D", "text": "443"},
            ],
            "primary_concept_id": "http",
            "difficulty": "基础",
            "source_refs": [{"source_type": "notebook", "source_id": "chunk-1", "title": "HTTP 笔记"}],
            "answer_key": {
                "correct_option": "C",
                "explanation": "HTTP 的默认端口是 80。",
                "option_rationales": {"C": "80 是 HTTP 默认端口。"},
            },
            "rubric": {"common_misconceptions": ["把 443 当成 HTTP 默认端口"]},
            "generation_source": "practice_generation",
        }
        with patch(
            "app.persistence.repositories.question_items.upsert_question_bank_item_records",
            side_effect=fake_upsert,
        ), patch(
            "app.persistence.repositories.question_items.list_question_bank_item_records",
            side_effect=fake_list,
        ):
            item_id = repo.create_question_item(payload)
            similar = repo.find_similar(payload, limit=3)

        self.assertEqual(item_id, "qgen-q1")
        self.assertEqual(saved_payloads[0][0]["subject_id"], "network")
        self.assertEqual(saved_payloads[0][0]["question"], payload["stem"])
        self.assertEqual(saved_payloads[0][0]["knowledge_point"], "http")
        self.assertEqual(similar[0]["id"], "existing-q1")


if __name__ == "__main__":
    unittest.main()
