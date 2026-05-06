from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from app.domains.practice.generation import build_mixed_practice_items_with_status
from app.orchestration.graphs.question_generation.schemas import (
    AnswerKey,
    AnswerOption,
    ItemBlueprint,
    QuestionCandidate,
    Rubric,
    SourceRef,
)
from app.orchestration.graphs.shared.schemas import LearningEvent
from app.shared.schemas.contracts import PracticeRecommendation


class QuestionCandidateGenerator(Protocol):
    def generate(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
    ) -> list[QuestionCandidate]:
        """Generate serializable question candidates without mutating state."""


@dataclass(frozen=True)
class QuestionCandidateGenerationResult:
    """Contract-safe candidate generation output.

    ``status`` carries normalized counts from legacy generators without leaking
    raw runtime payloads into graph state.
    """

    candidates: list[QuestionCandidate] = field(default_factory=list)
    status: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeterministicQuestionCandidateGenerator:
    """Test-safe adapter used until legacy quiz generation is wrapped."""

    def generate(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
    ) -> list[QuestionCandidate]:
        return self.generate_with_status(blueprint=blueprint, source_refs=source_refs).candidates

    def generate_with_status(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
    ) -> QuestionCandidateGenerationResult:
        candidates = [
            _build_candidate(
                blueprint=blueprint,
                source_refs=source_refs,
                index=index,
            )
            for index in range(blueprint.count)
        ]
        return QuestionCandidateGenerationResult(
            candidates=candidates,
            status={
                "generation_source": "deterministic_adapter",
                "requested_count": blueprint.count,
                "generated_count": len(candidates),
                "question_bank_count": 0,
                "ai_count": len(candidates),
                "fallback_count": 0,
                "partial": len(candidates) < blueprint.count,
                "degraded_reason": "",
            },
        )


@dataclass(frozen=True)
class EmptyQuestionCandidateGenerator:
    """Test adapter that represents an exhausted legacy generation chain."""

    degraded_reason: str = "question generation returned no items"

    def generate(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
    ) -> list[QuestionCandidate]:
        return self.generate_with_status(blueprint=blueprint, source_refs=source_refs).candidates

    def generate_with_status(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
    ) -> QuestionCandidateGenerationResult:
        return QuestionCandidateGenerationResult(
            candidates=[],
            status={
                "generation_source": "empty_adapter",
                "requested_count": blueprint.count,
                "generated_count": 0,
                "question_bank_count": 0,
                "ai_count": 0,
                "fallback_count": 0,
                "partial": True,
                "degraded_reason": self.degraded_reason,
            },
        )


@dataclass(frozen=True)
class LegacyPracticeQuestionCandidateGenerator:
    """Adapter around the existing practice generation service."""

    user_id: str = ""
    subject_id: str = "general"
    subject_name: str = "通用知识"
    original_question: str = ""
    model_name: str | None = None

    def generate(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
    ) -> list[QuestionCandidate]:
        return self.generate_with_status(blueprint=blueprint, source_refs=source_refs).candidates

    def generate_with_status(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
    ) -> QuestionCandidateGenerationResult:
        result = build_mixed_practice_items_with_status(
            subject_id=self.subject_id,
            subject_name=self.subject_name,
            topic=blueprint.concept_name,
            difficulty=blueprint.difficulty,
            count=blueprint.count,
            original_question=self.original_question or f"围绕「{blueprint.concept_name}」出题",
            user_style_name="",
            user_style_prompt="",
            short_term_context="",
            session_memory_context="",
            long_term_context="",
            model_name=self.model_name,
            rag_context=_rag_context_from_source_refs(source_refs),
            knowledge_points=[blueprint.concept_name],
        )
        candidates = [
            _practice_item_to_candidate(
                item=item,
                blueprint=blueprint,
                source_refs=source_refs,
            )
            for item in result.items
        ]
        raw_status = dict(getattr(result, "status", {}) or {})
        status = {
            "generation_source": "practice_generation",
            "production_output_mapped": True,
            "requested_count": int(raw_status.get("requested_count") or blueprint.count),
            "generated_count": len(candidates),
            "question_bank_count": int(raw_status.get("question_bank_count") or 0),
            "ai_count": int(raw_status.get("ai_count") or 0),
            "fallback_count": int(raw_status.get("fallback_count") or 0),
            "partial": bool(raw_status.get("partial", False)) or len(candidates) < blueprint.count,
            "degraded_reason": str(raw_status.get("degraded_reason") or ""),
        }
        return QuestionCandidateGenerationResult(candidates=candidates, status=status)


@dataclass
class InMemoryQuestionItemRepository:
    items: list[dict[str, Any]] = field(default_factory=list)

    def create_question_item(self, payload: dict[str, Any]) -> str:
        item_id = str(payload.get("id") or f"qitem-{uuid4()}")
        saved = {**payload, "id": item_id}
        self.items.append(saved)
        return item_id

    def find_similar(self, payload: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
        stem = str(payload.get("stem") or payload.get("question") or "").strip()
        if not stem:
            return []
        matches = [item for item in self.items if str(item.get("stem") or "").strip() == stem]
        return matches[:limit]


@dataclass
class InMemoryLearningEventRepository:
    events: list[LearningEvent] = field(default_factory=list)

    def append(self, event: LearningEvent) -> str:
        self.events.append(event)
        return event.id

    def list_for_user(self, *, user_id: str, limit: int = 100) -> list[LearningEvent]:
        return [event for event in self.events if event.user_id == user_id][:limit]


def _build_candidate(
    *,
    blueprint: ItemBlueprint,
    source_refs: list[SourceRef],
    index: int,
) -> QuestionCandidate:
    concept = blueprint.concept_name.strip() or blueprint.primary_concept_id
    subject_variant = _subject_candidate_variant(concept, index)
    if subject_variant is not None:
        stem, raw_options, correct, explanation, rationales, misconceptions = subject_variant
    elif "http" in concept.lower() or "端口" in concept:
        variants = [
            (
                "HTTP 协议的默认端口号是哪个？",
                [("A", "21"), ("B", "53"), ("C", "80"), ("D", "443")],
                "C",
                "HTTP 的默认端口是 80，HTTPS 的默认端口才是 443。",
                {
                    "A": "21 通常用于 FTP 控制连接。",
                    "B": "53 通常用于 DNS。",
                    "C": "80 是 HTTP 的默认端口。",
                    "D": "443 是 HTTPS 的默认端口。",
                },
                ["区分 HTTP 与 HTTPS 默认端口", "避免把 80 和 443 混淆"],
            ),
            (
                "浏览器访问 http://example.com 且未显式写端口时，通常会连接哪个端口？",
                [("A", "25"), ("B", "80"), ("C", "110"), ("D", "443")],
                "B",
                "URL 使用 http scheme 且未写端口时，客户端通常按 HTTP 默认端口 80 连接。",
                {
                    "A": "25 通常用于 SMTP。",
                    "B": "80 是 HTTP 的默认端口。",
                    "C": "110 通常用于 POP3。",
                    "D": "443 是 HTTPS 的默认端口。",
                },
                ["识别 URL scheme", "区分常见协议端口"],
            ),
        ]
        stem, raw_options, correct, explanation, rationales, misconceptions = variants[index % len(variants)]
    else:
        stem = f"关于「{concept}」的学习，哪一项最能说明已经理解核心概念？"
        raw_options = [
            ("A", "能用自己的话解释并解决变式问题"),
            ("B", "只觉得概念看起来熟悉"),
            ("C", "看到答案后觉得自己会"),
            ("D", "完全不做练习也不复盘"),
        ]
        correct = "A"
        explanation = f"真正理解「{concept}」通常表现为能解释、能迁移、能处理变式问题。"
        rationales = {
            "A": "解释和迁移能检验理解深度。",
            "B": "熟悉感容易造成掌握错觉。",
            "C": "看答案后会不等于独立会做。",
            "D": "缺少练习和复盘无法验证掌握。",
        }
        misconceptions = ["把熟悉感当成掌握", "只背答案不理解条件"]

    options = [AnswerOption(key=key, text=text) for key, text in raw_options]  # type: ignore[arg-type]
    correct_text = next(option.text for option in options if option.key == correct)
    return QuestionCandidate(
        stem=stem,
        options=options,
        primary_concept_id=blueprint.primary_concept_id,
        difficulty=blueprint.difficulty,
        source_refs=source_refs,
        answer_key=AnswerKey(
            correct_option=correct,  # type: ignore[arg-type]
            correct_option_text=correct_text,
            explanation=explanation,
            option_rationales=rationales,  # type: ignore[arg-type]
        ),
        rubric=Rubric(
            criteria=["single_correct_option", "concept_alignment", "complete_rationales"],
            full_credit=f"选择 {correct} 并能说明：{explanation}",
            common_misconceptions=misconceptions,
        ),
    )


def _practice_item_to_candidate(
    *,
    item: PracticeRecommendation,
    blueprint: ItemBlueprint,
    source_refs: list[SourceRef],
) -> QuestionCandidate:
    options = [
        AnswerOption(key=str(option["key"]), text=str(option["text"]))  # type: ignore[arg-type]
        for option in item.options
    ]
    correct_text = next(
        (option.text for option in options if option.key == item.correct_option),
        str(item.correct_option),
    )
    return QuestionCandidate(
        stem=item.question,
        options=options,
        primary_concept_id=blueprint.primary_concept_id,
        difficulty=item.difficulty or blueprint.difficulty,
        source_refs=source_refs
        or [
            SourceRef(
                source_type=item.source_type or "practice_generation",
                source_id=item.question_id,
                title=item.source_name or "",
            )
        ],
        answer_key=AnswerKey(
            correct_option=item.correct_option,  # type: ignore[arg-type]
            correct_option_text=correct_text,
            explanation=item.explanation,
            option_rationales=item.option_rationales,  # type: ignore[arg-type]
        ),
        rubric=Rubric(
            criteria=["single_correct_option", "complete_explanation", "option_rationales"],
            full_credit=f"选择 {item.correct_option} 并能说明：{item.explanation}",
            common_misconceptions=[
                rationale
                for key, rationale in item.option_rationales.items()
                if key != item.correct_option and rationale
            ][:3],
        ),
        generation_source="practice_generation",
    )


def _subject_candidate_variant(
    concept: str,
    index: int,
) -> tuple[str, list[tuple[str, str]], str, str, dict[str, str], list[str]] | None:
    compact = concept.replace(" ", "")
    if not any(term in compact for term in ("数据结构与算法", "数据结构", "数据与结构", "算法")):
        return None
    variants = [
        (
            "在数组和链表的对比中，哪一项说法最准确？",
            [("A", "数组适合随机访问，链表更适合频繁插入删除"), ("B", "链表一定比数组查询更快"), ("C", "数组不需要连续内存空间"), ("D", "链表不能动态扩展")],
            "A",
            "数组支持按下标随机访问；链表插入删除更灵活，但按位置访问通常要遍历。",
            {"A": "准确体现两者核心取舍。", "B": "链表按位置查询通常需要遍历。", "C": "数组通常依赖连续内存。", "D": "链表可以动态扩展。"},
            ["混淆数组和链表的访问成本"],
        ),
        (
            "栈这种数据结构最典型的访问规则是什么？",
            [("A", "先进先出"), ("B", "后进先出"), ("C", "按优先级先出"), ("D", "随机访问任意位置")],
            "B",
            "栈的核心规则是 LIFO：后进入栈的元素先被弹出。",
            {"A": "先进先出是队列。", "B": "后进先出是栈。", "C": "这是优先队列。", "D": "这不是栈的核心模型。"},
            ["把栈和队列规则混淆"],
        ),
        (
            "关于哈希表冲突，哪种理解是正确的？",
            [("A", "只要使用哈希函数就不会发生冲突"), ("B", "不同 key 可能映射到同一个桶，需要冲突处理"), ("C", "冲突只会发生在链表中"), ("D", "冲突一定说明哈希表实现错误")],
            "B",
            "哈希空间有限，不同 key 可能映射到同一位置，因此需要冲突处理策略。",
            {"A": "哈希函数不能保证完全无冲突。", "B": "这是哈希冲突的基本含义。", "C": "冲突是哈希表问题。", "D": "冲突是正常现象。"},
            ["以为哈希表不会冲突"],
        ),
        (
            "二叉树的中序遍历顺序通常是？",
            [("A", "根节点、左子树、右子树"), ("B", "左子树、根节点、右子树"), ("C", "左子树、右子树、根节点"), ("D", "按层从上到下访问")],
            "B",
            "中序遍历顺序是左子树、根节点、右子树。",
            {"A": "这是前序遍历。", "B": "这是中序遍历。", "C": "这是后序遍历。", "D": "这是层序遍历。"},
            ["混淆前序、中序、后序"],
        ),
        (
            "快速排序的平均时间复杂度通常是？",
            [("A", "O(1)"), ("B", "O(n)"), ("C", "O(n log n)"), ("D", "O(n² log n)")],
            "C",
            "快速排序平均时间复杂度通常为 O(n log n)，极端情况下可能退化到 O(n²)。",
            {"A": "排序不可能常数时间完成。", "B": "比较排序通常不是线性。", "C": "这是平均复杂度。", "D": "这不是常见复杂度。"},
            ["只记最坏情况而忽略平均情况"],
        ),
    ]
    return variants[index % len(variants)]


def _rag_context_from_source_refs(source_refs: list[SourceRef]) -> str:
    if not source_refs:
        return "（本轮未检索到额外知识库材料）"
    return "\n".join(
        f"- {ref.source_type}:{ref.source_id} {ref.title}".strip()
        for ref in source_refs[:5]
    )
