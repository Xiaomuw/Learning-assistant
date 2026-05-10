from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from app.domains.practice.generation import (
    build_mixed_practice_items_with_status,
    repair_practice_items_with_status,
)
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
class QuestionCandidateRepairResult:
    candidates: list[QuestionCandidate] = field(default_factory=list)
    status: dict[str, Any] = field(default_factory=dict)


class QuestionCandidateRepairer(Protocol):
    def repair(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
        candidates: list[QuestionCandidate],
        issues: list[str],
        forbidden_signatures: list[str],
    ) -> list[QuestionCandidate]:
        """Repair candidate questions after quality gate feedback."""


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

    def repair(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
        candidates: list[QuestionCandidate],
        issues: list[str],
        forbidden_signatures: list[str],
    ) -> list[QuestionCandidate]:
        return self.repair_with_status(
            blueprint=blueprint,
            source_refs=source_refs,
            candidates=candidates,
            issues=issues,
            forbidden_signatures=forbidden_signatures,
        ).candidates

    def repair_with_status(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
        candidates: list[QuestionCandidate],
        issues: list[str],
        forbidden_signatures: list[str],
    ) -> QuestionCandidateRepairResult:
        repaired = [
            _build_candidate(
                blueprint=blueprint,
                source_refs=source_refs,
                index=index,
            )
            for index in range(0, max(blueprint.count * 6, blueprint.count + len(forbidden_signatures)))
        ]
        return QuestionCandidateRepairResult(
            candidates=repaired,
            status={
                "repair_source": "deterministic_adapter",
                "repair_model_used": False,
                "repair_generated_count": len(repaired),
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

    def repair(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
        candidates: list[QuestionCandidate],
        issues: list[str],
        forbidden_signatures: list[str],
    ) -> list[QuestionCandidate]:
        return []


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
            "ai_generation_skipped": bool(raw_status.get("ai_generation_skipped", False)),
            "ai_model_used": bool(raw_status.get("ai_model_used", False)),
            "model_name": str(raw_status.get("model_name") or ""),
            "model_timeout_seconds": raw_status.get("model_timeout_seconds"),
        }
        return QuestionCandidateGenerationResult(candidates=candidates, status=status)

    def repair(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
        candidates: list[QuestionCandidate],
        issues: list[str],
        forbidden_signatures: list[str],
    ) -> list[QuestionCandidate]:
        return self.repair_with_status(
            blueprint=blueprint,
            source_refs=source_refs,
            candidates=candidates,
            issues=issues,
            forbidden_signatures=forbidden_signatures,
        ).candidates

    def repair_with_status(
        self,
        *,
        blueprint: ItemBlueprint,
        source_refs: list[SourceRef],
        candidates: list[QuestionCandidate],
        issues: list[str],
        forbidden_signatures: list[str],
    ) -> QuestionCandidateRepairResult:
        result = repair_practice_items_with_status(
            subject_id=self.subject_id,
            subject_name=self.subject_name,
            topic=blueprint.concept_name,
            difficulty=blueprint.difficulty,
            count=blueprint.count,
            original_question=self.original_question or f"围绕「{blueprint.concept_name}」修复题包",
            quality_issues=issues,
            forbidden_stems=[candidate.stem for candidate in candidates],
            user_style_name="",
            user_style_prompt="",
            short_term_context="",
            session_memory_context="",
            long_term_context="",
            model_name=self.model_name,
            rag_context=_rag_context_from_source_refs(source_refs),
        )
        repaired = [
            _practice_item_to_candidate(
                item=item,
                blueprint=blueprint,
                source_refs=source_refs,
            )
            for item in result.items
        ]
        raw_status = dict(getattr(result, "status", {}) or {})
        return QuestionCandidateRepairResult(
            candidates=repaired,
            status={
                "repair_source": "practice_generation_repair",
                "repair_model_used": bool(raw_status.get("repair_model_used", False)),
                "repair_model_name": str(raw_status.get("repair_model_name") or ""),
                "repair_model_timeout_seconds": raw_status.get("repair_model_timeout_seconds"),
                "repair_model_skipped": bool(raw_status.get("repair_model_skipped", False)),
                "repair_generated_count": len(repaired),
                "repair_fallback_count": int(raw_status.get("repair_fallback_count") or 0),
                "repair_degraded": bool(raw_status.get("repair_degraded", False)),
                "repair_ai_generation_failed": bool(raw_status.get("repair_ai_generation_failed", False)),
                "degraded_reason": str(raw_status.get("degraded_reason") or ""),
            },
        )


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
    subject_id = str(blueprint.constraints.get("subject_id") or "")
    specific_variant = _specific_topic_candidate_variant(concept, index)
    if specific_variant is not None:
        stem, raw_options, correct, explanation, rationales, misconceptions = specific_variant
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
        subject_variant = _subject_candidate_variant(concept, index, subject_id=subject_id)
        if subject_variant is not None:
            stem, raw_options, correct, explanation, rationales, misconceptions = subject_variant
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
        source_refs=_practice_item_source_refs(item=item, source_refs=source_refs),
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


def _practice_item_source_refs(
    *,
    item: PracticeRecommendation,
    source_refs: list[SourceRef],
) -> list[SourceRef]:
    refs: list[SourceRef] = list(source_refs)
    seen = {(ref.source_type, ref.source_id) for ref in refs}
    if item.question_id:
        candidate = SourceRef(
            source_type=item.source_type or "practice_generation",
            source_id=item.question_id,
            title=item.source_name or "",
        )
        if (candidate.source_type, candidate.source_id) not in seen:
            refs.append(candidate)

    return refs


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

    if "进程调度" in compact or "调度" in compact:
        variants = [
            (
                "进程调度最核心的目标通常是什么？",
                [("A", "在公平性、响应时间和吞吐量之间取得平衡"), ("B", "让所有进程永久占有 CPU"), ("C", "跳过就绪队列直接终止进程"), ("D", "只管理磁盘文件目录")],
                "A",
                "进程调度负责从就绪进程中选择运行者，常要权衡公平性、响应时间和系统吞吐量。",
                {"A": "这是进程调度的核心取舍。", "B": "进程长期独占 CPU 会破坏多任务。", "C": "调度不会随意终止就绪进程。", "D": "文件目录属于文件系统管理。"},
                ["把调度理解成简单排队", "忽略调度指标之间的取舍"],
            ),
            (
                "时间片轮转调度最适合体现哪种思想？",
                [("A", "让就绪进程按时间片轮流获得 CPU"), ("B", "只让最晚到达的进程运行"), ("C", "让一个进程一直运行到系统关闭"), ("D", "只根据文件大小决定 CPU 分配")],
                "A",
                "时间片轮转通过周期性切换 CPU 使用权，让多个就绪进程获得较公平的响应机会。",
                {"A": "这正是时间片轮转的特点。", "B": "这不是 RR 的调度规则。", "C": "长期独占会让交互响应变差。", "D": "CPU 调度不按文件大小决定。"},
                ["混淆时间片轮转和先来先服务", "忽略上下文切换"],
            ),
            (
                "短作业优先调度的主要优点是什么？",
                [("A", "通常能降低平均等待时间"), ("B", "一定不会让长作业饥饿"), ("C", "不需要估计作业运行时间"), ("D", "能替代内存管理")],
                "A",
                "短作业优先优先运行预计时间短的作业，通常可以降低平均等待时间，但可能导致长作业饥饿。",
                {"A": "这是 SJF 的常见优势。", "B": "长作业可能长期等待。", "C": "SJF 依赖对运行时间的估计。", "D": "调度算法不能替代内存管理。"},
                ["只记优点而忽略饥饿问题"],
            ),
            (
                "优先级调度中，老化机制主要用于解决什么问题？",
                [("A", "低优先级进程长期得不到 CPU 的饥饿问题"), ("B", "所有进程都立即结束的问题"), ("C", "就绪队列永远为空的问题"), ("D", "时间片无法被设置的问题")],
                "A",
                "老化会逐步提高等待过久进程的优先级，从而缓解低优先级进程饥饿。",
                {"A": "老化机制正是为缓解饥饿。", "B": "老化不会让进程直接结束。", "C": "老化处理的是长期等待，不是清空就绪队列。", "D": "时间片设置不是老化机制的核心目标。"},
                ["把优先级高低看成永远不变"],
            ),
            (
                "抢占式调度和非抢占式调度的关键区别是什么？",
                [("A", "运行中的进程能否被系统中断并让出 CPU"), ("B", "是否必须等待进程主动放弃 CPU"), ("C", "是否完全不发生上下文切换"), ("D", "是否只能运行一个程序")],
                "A",
                "抢占式调度允许系统在时机到来时剥夺当前进程的 CPU，非抢占式通常等进程主动让出或结束。",
                {"A": "这是两类调度的关键差异。", "B": "这描述的是非抢占式的一种表现，不是两者共同区别。", "C": "两类调度都可能发生上下文切换。", "D": "现代系统可通过调度支持多任务。"},
                ["混淆抢占条件和进程状态转换"],
            ),
        ]
        return variants[index % len(variants)]

    if "流水线" in compact or "pipeline" in compact:
        variants = [
            (
                "CPU 流水线技术主要提升的是什么？",
                [("A", "指令吞吐率"), ("B", "磁盘容量"), ("C", "网络带宽"), ("D", "显示器分辨率")],
                "A",
                "流水线把指令执行拆成多个阶段并重叠执行，主要提升单位时间完成的指令数量。",
                {"A": "流水线主要提升吞吐率。", "B": "磁盘容量不是 CPU 流水线目标。", "C": "网络带宽与流水线无直接关系。", "D": "显示器分辨率与指令执行无关。"},
                ["把单条指令延迟和整体吞吐率混淆"],
            ),
            (
                "流水线中的数据相关通常指什么？",
                [("A", "后一条指令需要前一条指令尚未写回的结果"), ("B", "两个流水段的名称相似"), ("C", "所有指令完全没有操作数"), ("D", "取指阶段永远不需要等待")],
                "A",
                "数据相关发生在指令之间存在数据依赖，后续指令需要等待或转发前序结果。",
                {"A": "这是典型 RAW 数据相关。", "B": "名称相似不是数据依赖。", "C": "指令没有操作数不是数据相关的定义。", "D": "取指是否等待不是数据相关的核心。"},
                ["不区分数据相关和控制相关"],
            ),
            (
                "分支指令容易给流水线带来什么影响？",
                [("A", "控制相关，可能导致取错后续指令"), ("B", "让所有 Cache 永远命中"), ("C", "直接删除寄存器文件"), ("D", "强制关闭中断")],
                "A",
                "分支结果未确定前，流水线可能无法确认下一条应取的指令，因此会产生控制相关。",
                {"A": "这是分支带来的控制相关。", "B": "分支不会保证 Cache 命中。", "C": "寄存器文件不会被删除。", "D": "分支和中断不是一回事。"},
                ["把控制相关理解成数据相关"],
            ),
            (
                "流水线停顿通常意味着什么？",
                [("A", "某些阶段等待相关条件满足，不能继续推进"), ("B", "CPU 不再支持任何指令"), ("C", "主存容量变为 0"), ("D", "操作系统删除了进程表")],
                "A",
                "流水线停顿是为了处理结构、数据或控制相关，让后续阶段等待条件满足。",
                {"A": "停顿是处理相关冲突的常见手段。", "B": "停顿不是 CPU 失效。", "C": "主存容量不会因此变为 0。", "D": "进程表属于操作系统。"},
                ["把停顿理解成系统故障"],
            ),
            (
                "理想流水线加速比受限的主要原因是什么？",
                [("A", "阶段不均衡、相关冲突和流水线开销"), ("B", "每个阶段耗时完全相同"), ("C", "所有指令都没有依赖"), ("D", "流水线寄存器不产生任何开销")],
                "A",
                "实际流水线会受到阶段时间不均、冒险冲突和寄存器开销等限制，难以达到理想加速比。",
                {"A": "这些都会限制流水线效果。", "B": "完全均衡反而更接近理想情况。", "C": "没有依赖会减少限制，不是限制原因。", "D": "流水线寄存器通常会带来额外开销。"},
                ["只按阶段数估算加速比而忽略开销"],
            ),
        ]
        return variants[index % len(variants)]

    return None


def _subject_candidate_variant(
    concept: str,
    index: int,
    *,
    subject_id: str = "",
) -> tuple[str, list[tuple[str, str]], str, str, dict[str, str], list[str]] | None:
    compact = concept.replace(" ", "")
    normalized_subject_id = str(subject_id or "").strip()
    if normalized_subject_id == "computer-network" or any(term in compact for term in ("计算机网络", "网络协议", "网络")):
        variants = [
            (
                "在 TCP/IP 分层模型中，HTTP 通常属于哪一层协议？",
                [("A", "应用层"), ("B", "传输层"), ("C", "网络层"), ("D", "数据链路层")],
                "A",
                "HTTP 负责应用之间的请求与响应语义，通常归入应用层；它底层可以依赖 TCP 或 QUIC。",
                {"A": "HTTP 是典型应用层协议。", "B": "TCP 才是传输层协议。", "C": "IP 属于网络层。", "D": "以太网等更接近数据链路层。"},
                ["把 HTTP 当成传输层协议", "混淆 TCP/IP 分层职责"],
            ),
            (
                "DNS 在一次网页访问中最核心的作用是什么？",
                [("A", "把域名解析为可通信的 IP 地址"), ("B", "加密浏览器和服务器之间的报文"), ("C", "保证 TCP 连接永远不断开"), ("D", "替代 HTTP 返回网页内容")],
                "A",
                "DNS 的核心职责是名称解析，把用户易记的域名转换为网络通信需要的 IP 地址。",
                {"A": "这是 DNS 的核心作用。", "B": "加密通常由 TLS/HTTPS 完成。", "C": "连接可靠性主要由传输层机制处理。", "D": "DNS 不负责返回网页内容。"},
                ["把 DNS 和 HTTP 职责混淆", "误以为 DNS 负责加密或传输内容"],
            ),
            (
                "TCP 三次握手主要解决的问题是什么？",
                [("A", "建立双方都确认的可靠连接状态"), ("B", "把域名转换成 IP 地址"), ("C", "压缩网页资源体积"), ("D", "决定网页使用哪种字体")],
                "A",
                "TCP 三次握手用于让通信双方确认彼此收发能力和初始序列号，从而建立可靠连接状态。",
                {"A": "准确体现了三次握手的目的。", "B": "这是 DNS 的职责。", "C": "压缩属于应用或内容编码层面的优化。", "D": "字体选择与 TCP 建连无关。"},
                ["把 DNS 解析和 TCP 建连混在一起", "只记流程不理解建连目的"],
            ),
        ]
        return variants[index % len(variants)]

    if normalized_subject_id == "computer-organization" or any(term in compact for term in ("计算机组成", "组成原理", "计组")):
        variants = [
            (
                "存储层次结构的核心目的是什么？",
                [("A", "在速度、容量和成本之间取得平衡"), ("B", "让所有存储器速度完全相同"), ("C", "取消主存只保留寄存器"), ("D", "让磁盘直接替代 Cache")],
                "A",
                "寄存器、Cache、主存和外存形成层次，是为了在访问速度、容量和成本之间折中。",
                {"A": "这是存储层次结构的设计目标。", "B": "不同层级速度明显不同。", "C": "主存仍是程序运行的关键层。", "D": "磁盘速度远慢于 Cache。"},
                ["只看容量而忽略速度和成本"],
            ),
            (
                "CPU 流水线技术主要想提升什么？",
                [("A", "指令吞吐率"), ("B", "硬盘容量"), ("C", "网络带宽"), ("D", "文件目录数量")],
                "A",
                "流水线把取指、译码、执行等阶段重叠起来，主要提升单位时间完成的指令数量。",
                {"A": "流水线主要提升吞吐率。", "B": "硬盘容量不是 CPU 流水线目标。", "C": "网络带宽不由流水线直接决定。", "D": "文件目录属于文件系统。"},
                ["把吞吐率和单条指令延迟混淆"],
            ),
            (
                "Cache 利用程序局部性，主要是为了什么？",
                [("A", "减少 CPU 访问主存的平均等待时间"), ("B", "替代所有外存"), ("C", "保证每次访问都不会缺失"), ("D", "让主存容量自动变为无限大")],
                "A",
                "Cache 依赖时间局部性和空间局部性，把近期或邻近数据放到更快的存储层，降低平均访存时间。",
                {"A": "这是 Cache 的核心作用。", "B": "Cache 容量有限，不能替代外存。", "C": "Cache 仍可能 miss。", "D": "主存容量由硬件配置决定，不会自动无限增长。"},
                ["以为 Cache 命中率必然是 100%"],
            ),
            (
                "指令周期通常围绕哪些基本阶段展开？",
                [("A", "取指、译码、执行等阶段"), ("B", "等待用户输入、刷新界面、关闭窗口"), ("C", "容量扩展、权限审核、日志归档"), ("D", "创建目录、移动文件、清空回收站")],
                "A",
                "一条机器指令通常要经历取指、译码、执行、访存和写回等阶段。",
                {"A": "这些是指令执行的基本阶段。", "B": "这不是机器指令在 CPU 内部执行的阶段。", "C": "这些不是指令周期的标准阶段。", "D": "这些是面向用户的文件操作，不是指令周期。"},
                ["把程序执行流程和网络流程混在一起"],
            ),
            (
                "补码表示最重要的好处之一是什么？",
                [("A", "让有符号整数加减法可以用统一的二进制加法处理"), ("B", "让浮点数不再需要规格化"), ("C", "让所有溢出都自动消失"), ("D", "让符号位不再参与编码")],
                "A",
                "补码把符号和数值编码统一起来，使有符号整数加减法能较方便地由同一套加法电路处理。",
                {"A": "这是补码设计的核心优势。", "B": "浮点规格化是另一套表示问题。", "C": "补码不能消除有限位宽下的溢出。", "D": "符号信息仍然通过最高位参与编码。"},
                ["混淆补码和浮点数表示"],
            ),
        ]
        return variants[index % len(variants)]

    if normalized_subject_id == "operating-system" or any(term in compact for term in ("操作系统", "进程", "线程", "调度", "死锁", "内存管理", "文件系统")):
        variants = [
            (
                "进程和线程的关系，哪一项更准确？",
                [("A", "进程是资源分配单位，线程是 CPU 调度执行单位"), ("B", "线程一定拥有独立完整地址空间"), ("C", "进程和线程完全没有区别"), ("D", "一个进程一定只能有一个线程")],
                "A",
                "现代操作系统中，进程通常承载资源，线程是调度执行的基本单位，同一进程内线程共享部分资源。",
                {"A": "准确概括了进程和线程的分工。", "B": "同进程线程通常共享地址空间。", "C": "两者职责不同。", "D": "一个进程可以包含多个线程。"},
                ["混淆资源分配单位和调度单位"],
            ),
            (
                "死锁产生通常需要同时满足哪些必要条件？",
                [("A", "互斥、占有并等待、不可抢占、循环等待"), ("B", "取指、译码、执行、写回"), ("C", "域名解析、路由转发、拥塞控制"), ("D", "排序、查找、哈希、遍历")],
                "A",
                "死锁的经典四个必要条件是互斥、占有并等待、不可抢占和循环等待。",
                {"A": "这是死锁四个必要条件。", "B": "这是指令执行相关流程。", "C": "这是计算机网络相关概念。", "D": "这是数据结构与算法相关操作。"},
                ["把死锁条件和其他课程概念混淆"],
            ),
            (
                "虚拟内存的主要作用是什么？",
                [("A", "为进程提供连续统一的地址空间并按需映射到物理内存"), ("B", "让所有页面永远驻留物理内存"), ("C", "让每个进程共享同一段地址空间"), ("D", "让内存访问不再需要地址转换")],
                "A",
                "虚拟内存通过地址转换和按需调页，让进程看到相对连续的逻辑地址空间，并提升内存管理灵活性。",
                {"A": "这是虚拟内存的核心作用。", "B": "按需调页意味着页面不一定永远驻留。", "C": "进程通常拥有相互隔离的虚拟地址空间。", "D": "虚拟地址仍然需要转换为物理地址。"},
                ["只把虚拟内存理解成扩大内存容量"],
            ),
            (
                "信号量常用于解决哪类问题？",
                [("A", "进程或线程之间的同步与互斥"), ("B", "让所有临界区无需保护"), ("C", "让阻塞队列永久为空"), ("D", "让所有进程同时进入同一临界区")],
                "A",
                "信号量通过 P/V 操作协调并发执行，常用于实现同步和互斥。",
                {"A": "这是信号量的典型用途。", "B": "临界区仍然需要同步机制保护。", "C": "阻塞队列是否为空取决于资源和等待情况。", "D": "互斥要求同一时刻通常只能有一个执行流进入临界区。"},
                ["混淆同步和通信协议"],
            ),
            (
                "文件系统最核心的职责是什么？",
                [("A", "组织、命名、存储和访问文件数据"), ("B", "决定进程的时间片长度"), ("C", "让所有文件不占用外存空间"), ("D", "让目录结构只能有一层")],
                "A",
                "文件系统负责文件和目录的组织、命名、权限、存储分配以及数据访问。",
                {"A": "这是文件系统的核心职责。", "B": "时间片长度属于处理机调度策略。", "C": "文件数据通常需要占用存储空间。", "D": "目录结构可以是多层组织。"},
                ["把文件系统和数据库或网络协议混淆"],
            ),
        ]
        return variants[index % len(variants)]

    if normalized_subject_id != "data-structure" and not any(term in compact for term in ("数据结构与算法", "数据结构", "数据与结构", "算法")):
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
