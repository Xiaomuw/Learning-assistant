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
            "question_bank_unavailable": bool(raw_status.get("question_bank_unavailable", False)),
            "question_bank_error_type": str(raw_status.get("question_bank_error_type") or ""),
            "question_bank_error_count": int(raw_status.get("question_bank_error_count") or 0),
            "ai_generation_failed": bool(raw_status.get("ai_generation_failed", False)),
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
    specific_variant = _specific_topic_candidate_variant(concept, index)
    subject_variant = _subject_candidate_variant(concept, index)
    if specific_variant is not None:
        stem, raw_options, correct, explanation, rationales, misconceptions = specific_variant
    elif subject_variant is not None:
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
        variants = [
            (
                f"关于「{concept}」的学习，哪一项最能说明已经理解核心概念？",
                [
                    ("A", "能用自己的话解释并解决变式问题"),
                    ("B", "只觉得概念看起来熟悉"),
                    ("C", "看到答案后觉得自己会"),
                    ("D", "完全不做练习也不复盘"),
                ],
                "A",
                f"真正理解「{concept}」通常表现为能解释、能迁移、能处理变式问题。",
                {
                    "A": "解释和迁移能检验理解深度。",
                    "B": "熟悉感容易造成掌握错觉。",
                    "C": "看答案后会不等于独立会做。",
                    "D": "缺少练习和复盘无法验证掌握。",
                },
                ["把熟悉感当成掌握", "只背答案不理解条件"],
            ),
            (
                f"学习「{concept}」时，最适合先确认哪一类边界？",
                [
                    ("A", "概念适用场景和不适用场景"),
                    ("B", "只记住一个固定例题答案"),
                    ("C", "跳过定义直接刷难题"),
                    ("D", "看到熟悉词就认为已经掌握"),
                ],
                "A",
                f"学习「{concept}」要先分清定义、适用条件和典型场景，再进入变式练习。",
                {
                    "A": "边界和场景能帮助迁移到新题。",
                    "B": "固定答案不能覆盖变式。",
                    "C": "跳过定义会让后续判断失去依据。",
                    "D": "熟悉词不等于能独立判断。",
                },
                ["忽略适用边界", "把见过当成掌握"],
            ),
            (
                f"复盘「{concept}」错题时，哪种做法最能帮助下次迁移？",
                [
                    ("A", "写出错因和触发条件，再找一道变式题验证"),
                    ("B", "只把正确答案背下来"),
                    ("C", "跳过解析继续刷下一题"),
                    ("D", "只看题目关键词，不看条件"),
                ],
                "A",
                f"复盘「{concept}」要把错因、条件和变式验证串起来，才能提升迁移能力。",
                {
                    "A": "错因加变式验证能形成可迁移经验。",
                    "B": "背答案难以应对新题。",
                    "C": "不看解析会重复同类错误。",
                    "D": "只看关键词容易误判题意。",
                },
                ["只背答案", "不复盘错因"],
            ),
        ]
        stem, raw_options, correct, explanation, rationales, misconceptions = variants[index % len(variants)]

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
            full_credit=_directional_hint(explanation),
            common_misconceptions=misconceptions,
        ),
    )



def _directional_hint(explanation: str) -> str:
    detail = str(explanation or "").strip()
    if detail:
        return f"先根据题干中的关键条件排除明显不符合的选项，再用这个依据核对：{detail}"
    return "先找出题干中的关键条件，再逐项排除不符合条件的选项。"

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
            full_credit=_directional_hint(item.explanation),
            common_misconceptions=[
                rationale
                for key, rationale in item.option_rationales.items()
                if key != item.correct_option and rationale
            ][:3],
        ),
        generation_source="practice_generation",
    )


def _specific_topic_candidate_variant(
    concept: str,
    index: int,
) -> tuple[str, list[tuple[str, str]], str, str, dict[str, str], list[str]] | None:
    compact = concept.replace(" ", "").lower()
    if "stack" in compact or "栈" in compact:
        variants = [
            (
                "栈这种数据结构最典型的访问规则是什么？",
                [("A", "先进先出"), ("B", "后进先出"), ("C", "按优先级先出"), ("D", "随机访问任意位置")],
                "B",
                "栈的核心规则是 LIFO：后进入栈的元素会先被 pop 出来。",
                {"A": "先进先出是队列。", "B": "后进先出是栈。", "C": "这是优先队列。", "D": "栈不支持随机访问作为核心规则。"},
                ["把栈和队列规则混淆", "不理解 push/pop 顺序"],
            ),
            (
                "依次 push 1、push 2、pop、push 3、pop，最后一次 pop 得到什么？",
                [("A", "1"), ("B", "2"), ("C", "3"), ("D", "空栈")],
                "C",
                "栈是后进先出：先 pop 得到 2，再 push 3，最后一次 pop 得到 3。",
                {"A": "1 最早入栈，不会在最后一次 pop 先出。", "B": "2 已经在第一次 pop 出栈。", "C": "3 最后入栈，因此最后一次 pop 先出。", "D": "最后一次 pop 前栈中仍有 1 和 3。"},
                ["没有按 LIFO 模拟栈操作"],
            ),
        ]
        return variants[index % len(variants)]

    if "数据库索引" in compact or "databaseindex" in compact:
        variants = [
            (
                "数据库索引最主要的作用是什么？",
                [("A", "减少查询时需要扫描的数据范围"), ("B", "保证所有查询都不需要磁盘访问"), ("C", "自动消除所有重复数据"), ("D", "让写入操作一定更快")],
                "A",
                "数据库索引通常借助 B+树、哈希等结构缩小查找范围，从而减少全表扫描。",
                {"A": "这是索引优化查询的核心价值。", "B": "索引不能保证完全不访问磁盘。", "C": "去重通常依赖约束，不是普通索引的直接作用。", "D": "维护索引反而可能增加写入成本。"},
                ["把索引理解成万能加速器", "忽略索引维护成本"],
            ),
            (
                "关于联合索引的最左前缀原则，哪一项理解更准确？",
                [("A", "查询条件从索引最左列开始连续匹配时更容易用上索引"), ("B", "只要有任意一列条件就一定完整命中联合索引"), ("C", "联合索引只能包含一列"), ("D", "最左前缀原则只影响插入，不影响查询")],
                "A",
                "联合索引通常按列顺序组织，查询从最左列开始连续匹配时，优化器更容易利用索引。",
                {"A": "准确体现了最左前缀原则。", "B": "跳过最左列可能无法有效使用联合索引。", "C": "联合索引本来就是多列索引。", "D": "最左前缀主要影响查询是否能命中索引。"},
                ["以为联合索引任意列都等价", "忽略索引列顺序"],
            ),
        ]
        return variants[index % len(variants)]

    return None


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
