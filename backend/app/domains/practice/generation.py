from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from app.domains.practice.common import (
    dedupe_quiz_items,
    determine_difficulty,
    format_user_style_instruction,
    normalize_quiz_item,
)
from app.domains.practice.llm import get_generation_llm
from app.domains.practice.schemas import GeneratedQuizListOutput
from app.infrastructure.db.repositories.practice import (
    list_practice_recommendation_records,
    list_question_bank_item_records,
)
from app.infrastructure.db.repositories.users import get_user_memory_record
from app.infrastructure.llm.structured import invoke_with_schema
from app.shared.schemas.contracts import PracticeRecommendation


@dataclass(frozen=True)
class PracticeGenerationResult:
    items: list[PracticeRecommendation]
    status: dict[str, Any]

PRACTICE_GENERATION_SYSTEM_PROMPT = """\
你是一位严格但清晰的命题老师，请生成 {count} 道 4 选 1 的单选题。

## 当前知识点
{topic}

## 指定难度
{difficulty}

## 当前笔记本
{subject_name}

## 用户风格要求
{user_style_instruction}

## 最近对话上下文
{short_term_context}

## 当前会话摘要
{session_memory_context}

## 用户长期学习记忆
{long_term_context}

## RAG 检索到的知识库材料
{rag_context}

## 出题约束
1. 所有题必须是单选题，且只有 A/B/C/D 四个选项
2. 选项文本长度尽量均衡，不要出现明显一眼假的干扰项
3. 每题必须给出：
   - correct_option
   - explanation（完整解析）
   - option_rationales（A/B/C/D 每个选项为什么对或错）
4. 题目不要与用户原问题完全重复
5. 如果用户当前在复习或练习，优先围绕其薄弱点/当前目标设计

## 用户当前问题（避免重复）
{original_question}
"""

PRACTICE_GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", PRACTICE_GENERATION_SYSTEM_PROMPT),
        ("human", "请严格输出结构化单选题。"),
    ]
)


def _list_question_bank_items(
    *,
    subject_id: str | None = None,
    knowledge_points: list[str] | None = None,
    difficulty: str | None = None,
    years: list[int] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return [
        item.model_dump()
        for item in list_question_bank_item_records(
            subject_id=subject_id,
            knowledge_points=knowledge_points,
            difficulty=difficulty,
            years=years,
            limit=limit,
        )
    ]


def _list_practice_recommendations(user_id: str, *, subject_id: str | None = None, limit: int = 6) -> list[dict[str, Any]]:
    memory = get_user_memory_record(user_id)
    return [
        item.model_dump()
        for item in list_practice_recommendation_records(memory, subject_id=subject_id, limit=limit)
    ]


def _get_user_memory(user_id: str) -> dict[str, Any]:
    return get_user_memory_record(user_id).model_dump()


def _invoke_generation_chain(payload: dict[str, Any], *, model_name: str | None = None) -> GeneratedQuizListOutput:
    return invoke_with_schema(
        PRACTICE_GENERATION_PROMPT,
        get_generation_llm(
            temperature=0.7,
            model_name=model_name,
            timeout_seconds=12.0,
            max_retries=0,
        ),
        GeneratedQuizListOutput,
        payload,
        model_name=model_name,
    )


def _build_fallback_practice_item(
    *,
    topic: str,
    subject_name: str,
    difficulty: str,
    index: int = 0,
) -> PracticeRecommendation:
    topic_name = topic or subject_name or "综合"
    if "http" in topic_name.lower() or "端口" in topic_name:
        variants = [
            (
                "HTTP 协议的默认端口号是哪个？",
                [
                    {"key": "A", "text": "21"},
                    {"key": "B", "text": "53"},
                    {"key": "C", "text": "80"},
                    {"key": "D", "text": "443"},
                ],
                "C",
                "HTTP 的默认端口是 80，HTTPS 的默认端口才是 443。",
                {
                    "A": "21 通常用于 FTP 控制连接。",
                    "B": "53 通常用于 DNS。",
                    "C": "80 是 HTTP 的默认端口。",
                    "D": "443 是 HTTPS 的默认端口。",
                },
                "HTTP 默认端口",
            ),
            (
                "HTTPS 与 HTTP 的默认端口对应关系，哪一项正确？",
                [
                    {"key": "A", "text": "HTTP 80，HTTPS 443"},
                    {"key": "B", "text": "HTTP 443，HTTPS 80"},
                    {"key": "C", "text": "HTTP 53，HTTPS 21"},
                    {"key": "D", "text": "HTTP 22，HTTPS 25"},
                ],
                "A",
                "HTTP 默认端口是 80，HTTPS 默认端口是 443。",
                {
                    "A": "这组端口对应关系正确。",
                    "B": "把 HTTP 和 HTTPS 的默认端口写反了。",
                    "C": "53 常用于 DNS，21 常用于 FTP。",
                    "D": "22 常用于 SSH，25 常用于 SMTP。",
                },
                "HTTP/HTTPS 默认端口",
            ),
            (
                "浏览器访问 http://example.com 且未显式写端口时，通常会连接哪个端口？",
                [
                    {"key": "A", "text": "25"},
                    {"key": "B", "text": "80"},
                    {"key": "C", "text": "110"},
                    {"key": "D", "text": "443"},
                ],
                "B",
                "URL 使用 http scheme 且未写端口时，客户端通常按 HTTP 默认端口 80 连接。",
                {
                    "A": "25 通常用于 SMTP。",
                    "B": "80 是 HTTP 的默认端口。",
                    "C": "110 通常用于 POP3。",
                    "D": "443 是 HTTPS 的默认端口。",
                },
                "HTTP 默认端口",
            ),
        ]
        question, options, correct_option, explanation, rationales, knowledge_point = variants[index % len(variants)]
    elif _canonical_subject_key(topic_name) == "data-structure":
        variants = [
            (
                "在数组和链表的对比中，哪一项说法最准确？",
                [
                    {"key": "A", "text": "数组适合随机访问，链表更适合频繁插入删除"},
                    {"key": "B", "text": "链表一定比数组查询更快"},
                    {"key": "C", "text": "数组不需要连续内存空间"},
                    {"key": "D", "text": "链表不能动态扩展"},
                ],
                "A",
                "数组支持按下标 O(1) 随机访问，但插入删除可能移动元素；链表插入删除更灵活，但按位置访问通常要遍历。",
                {
                    "A": "准确体现了两者的核心取舍。",
                    "B": "链表按位置查询通常需要 O(n) 遍历。",
                    "C": "数组通常依赖连续内存空间。",
                    "D": "链表的优势之一就是动态扩展较灵活。",
                },
                "数组与链表",
            ),
            (
                "栈这种数据结构最典型的访问规则是什么？",
                [
                    {"key": "A", "text": "先进先出"},
                    {"key": "B", "text": "后进先出"},
                    {"key": "C", "text": "按优先级先出"},
                    {"key": "D", "text": "随机访问任意位置"},
                ],
                "B",
                "栈的核心规则是 LIFO：后进入栈的元素先被弹出。",
                {
                    "A": "先进先出是队列的典型规则。",
                    "B": "后进先出是栈的核心特征。",
                    "C": "按优先级先出更接近优先队列。",
                    "D": "随机访问不是栈的核心操作模型。",
                },
                "栈",
            ),
            (
                "关于哈希表冲突，哪种理解是正确的？",
                [
                    {"key": "A", "text": "只要使用哈希函数就不会发生冲突"},
                    {"key": "B", "text": "不同 key 可能映射到同一个桶，需要冲突处理"},
                    {"key": "C", "text": "冲突只会发生在链表中"},
                    {"key": "D", "text": "冲突一定说明哈希表实现错误"},
                ],
                "B",
                "哈希空间有限，不同 key 可能映射到同一位置，因此需要拉链法、开放寻址等冲突处理策略。",
                {
                    "A": "哈希函数不能保证完全无冲突。",
                    "B": "这是哈希冲突的基本含义。",
                    "C": "冲突是哈希表问题，不只发生在链表。",
                    "D": "冲突是正常现象，关键在处理策略。",
                },
                "哈希表冲突",
            ),
            (
                "二叉树的中序遍历顺序通常是？",
                [
                    {"key": "A", "text": "根节点、左子树、右子树"},
                    {"key": "B", "text": "左子树、根节点、右子树"},
                    {"key": "C", "text": "左子树、右子树、根节点"},
                    {"key": "D", "text": "按层从上到下访问"},
                ],
                "B",
                "二叉树中序遍历的顺序是左子树、根节点、右子树；二叉搜索树中序遍历通常能得到有序序列。",
                {
                    "A": "这是前序遍历。",
                    "B": "这是中序遍历。",
                    "C": "这是后序遍历。",
                    "D": "这是层序遍历。",
                },
                "二叉树遍历",
            ),
            (
                "在常见排序算法中，快速排序平均时间复杂度通常是？",
                [
                    {"key": "A", "text": "O(1)"},
                    {"key": "B", "text": "O(n)"},
                    {"key": "C", "text": "O(n log n)"},
                    {"key": "D", "text": "O(n² log n)"},
                ],
                "C",
                "快速排序通过分治划分区间，平均时间复杂度通常为 O(n log n)，但极端情况下可能退化到 O(n²)。",
                {
                    "A": "排序 n 个元素不可能常数时间完成。",
                    "B": "比较排序通常无法稳定达到 O(n)。",
                    "C": "这是快速排序的平均复杂度。",
                    "D": "这不是快速排序的常见复杂度表达。",
                },
                "快速排序复杂度",
            ),
        ]
        question, options, correct_option, explanation, rationales, knowledge_point = variants[index % len(variants)]
    elif _canonical_subject_key(topic_name) == "computer-network":
        variants = [
            (
                "TCP 与 UDP 的核心区别，哪一项最准确？",
                [
                    {"key": "A", "text": "TCP 面向连接且提供可靠传输，UDP 无连接且更轻量"},
                    {"key": "B", "text": "UDP 一定比 TCP 更可靠"},
                    {"key": "C", "text": "TCP 属于应用层，UDP 属于传输层"},
                    {"key": "D", "text": "TCP 和 UDP 都必须先三次握手"},
                ],
                "A",
                "TCP 提供面向连接的可靠字节流；UDP 无连接、开销更小，但可靠性通常由应用层自行保证。",
                {
                    "A": "准确概括了两者的常见取舍。",
                    "B": "UDP 本身不保证可靠传输。",
                    "C": "TCP 和 UDP 都属于传输层。",
                    "D": "三次握手是 TCP 建立连接的过程。",
                },
                "TCP 与 UDP",
            ),
            (
                "DNS 的主要作用是什么？",
                [
                    {"key": "A", "text": "把域名解析为 IP 地址"},
                    {"key": "B", "text": "加密 HTTP 报文内容"},
                    {"key": "C", "text": "控制 CPU 调度"},
                    {"key": "D", "text": "管理磁盘文件目录"},
                ],
                "A",
                "DNS 负责域名解析，让用户能通过域名找到对应的网络地址。",
                {
                    "A": "这是 DNS 的核心作用。",
                    "B": "HTTP 加密通常依赖 TLS。",
                    "C": "CPU 调度属于操作系统主题。",
                    "D": "文件目录管理属于文件系统主题。",
                },
                "DNS",
            ),
        ]
        question, options, correct_option, explanation, rationales, knowledge_point = variants[index % len(variants)]
    elif _canonical_subject_key(topic_name) == "computer-organization":
        variants = [
            (
                "存储层次结构的核心目的是什么？",
                [
                    {"key": "A", "text": "在成本、容量和访问速度之间取得平衡"},
                    {"key": "B", "text": "让所有存储器速度完全相同"},
                    {"key": "C", "text": "取消主存，只保留寄存器"},
                    {"key": "D", "text": "让磁盘直接替代 CPU 缓存"},
                ],
                "A",
                "寄存器、Cache、主存、外存形成层次结构，是为了在速度、容量和成本之间折中。",
                {
                    "A": "准确体现了存储层次的设计目标。",
                    "B": "不同层级速度并不相同。",
                    "C": "主存仍是程序运行的重要存储层。",
                    "D": "磁盘访问速度远慢于 Cache。",
                },
                "存储层次结构",
            ),
            (
                "CPU 流水线技术主要想提升什么？",
                [
                    {"key": "A", "text": "指令吞吐率"},
                    {"key": "B", "text": "硬盘容量"},
                    {"key": "C", "text": "显示器分辨率"},
                    {"key": "D", "text": "网络带宽"},
                ],
                "A",
                "流水线把指令执行拆成多个阶段并重叠执行，主要提升单位时间完成的指令数量。",
                {
                    "A": "这是流水线提升性能的关键。",
                    "B": "硬盘容量不是 CPU 流水线的目标。",
                    "C": "显示器分辨率与流水线无关。",
                    "D": "网络带宽不是流水线直接改善的对象。",
                },
                "CPU 流水线",
            ),
        ]
        question, options, correct_option, explanation, rationales, knowledge_point = variants[index % len(variants)]
    elif _canonical_subject_key(topic_name) == "operating-system":
        variants = [
            (
                "进程和线程的关系，哪一项更准确？",
                [
                    {"key": "A", "text": "线程是 CPU 调度的基本单位，进程是资源分配的基本单位"},
                    {"key": "B", "text": "进程和线程完全没有区别"},
                    {"key": "C", "text": "线程拥有独立的完整地址空间"},
                    {"key": "D", "text": "一个进程中一定只能有一个线程"},
                ],
                "A",
                "现代操作系统中，进程通常作为资源分配单位，线程作为调度执行单位；同一进程内线程共享进程资源。",
                {
                    "A": "准确概括了常见操作系统中的分工。",
                    "B": "二者在资源和调度层面有明显区别。",
                    "C": "同进程线程通常共享地址空间。",
                    "D": "一个进程可以包含多个线程。",
                },
                "进程与线程",
            ),
            (
                "死锁产生通常需要同时满足哪类条件？",
                [
                    {"key": "A", "text": "互斥、占有并等待、不可抢占、循环等待"},
                    {"key": "B", "text": "缓存命中、流水线、分支预测、乱序执行"},
                    {"key": "C", "text": "域名解析、路由转发、拥塞控制、三次握手"},
                    {"key": "D", "text": "排序、查找、遍历、哈希"},
                ],
                "A",
                "死锁的经典四个必要条件是互斥、占有并等待、不可抢占和循环等待。",
                {
                    "A": "这是死锁的四个必要条件。",
                    "B": "这些是计算机组成/体系结构相关概念。",
                    "C": "这些是计算机网络相关概念。",
                    "D": "这些是数据结构与算法相关操作。",
                },
                "死锁条件",
            ),
        ]
        question, options, correct_option, explanation, rationales, knowledge_point = variants[index % len(variants)]
    else:
        variants = [
            (
                f"关于「{topic_name}」的学习方法，哪一项最适合作为第一步？",
                [
                    {"key": "A", "text": "先理解核心定义和适用场景"},
                    {"key": "B", "text": "直接背所有细节，不区分重点"},
                    {"key": "C", "text": "只做题，不回看概念"},
                    {"key": "D", "text": "跳过基础，直接看综合难题"},
                ],
                "A",
                "学习一个知识点时，应先理解核心定义、边界和典型场景，再进入练习。",
                {
                    "A": "这是建立知识框架的合理起点。",
                    "B": "死记细节容易缺少理解。",
                    "C": "只做题容易形成碎片化记忆。",
                    "D": "跳过基础会增加理解成本。",
                },
            ),
            (
                f"复习「{topic_name}」时，哪种做法最能帮助发现薄弱点？",
                [
                    {"key": "A", "text": "只看自己已经会的内容"},
                    {"key": "B", "text": "记录错题原因并回到概念定位问题"},
                    {"key": "C", "text": "跳过解析直接刷下一题"},
                    {"key": "D", "text": "只背答案不看题干条件"},
                ],
                "B",
                "复习时要把错题和概念重新连接起来，才能定位薄弱点。",
                {
                    "A": "只看会的内容无法暴露问题。",
                    "B": "错因记录加概念回看有助于精准补弱。",
                    "C": "跳过解析会重复同类错误。",
                    "D": "只背答案无法迁移到新题。",
                },
            ),
            (
                f"判断自己是否真正掌握「{topic_name}」，哪一项最可靠？",
                [
                    {"key": "A", "text": "能用自己的话解释并解决变式问题"},
                    {"key": "B", "text": "只觉得概念看起来熟悉"},
                    {"key": "C", "text": "看到答案后觉得自己会"},
                    {"key": "D", "text": "完全不做练习也不复盘"},
                ],
                "A",
                "能解释、能迁移、能处理变式，通常比“看起来熟悉”更能说明掌握。",
                {
                    "A": "解释和迁移能检验理解深度。",
                    "B": "熟悉感容易造成掌握错觉。",
                    "C": "看答案后会不等于独立会做。",
                    "D": "缺少练习和复盘无法验证掌握。",
                },
            ),
        ]
        question, options, correct_option, explanation, rationales = variants[index % len(variants)]
        knowledge_point = topic_name

    return PracticeRecommendation(
        question_id=f"fallback-{uuid.uuid4()}",
        question=question,
        options=options,
        correct_option=correct_option,
        explanation=explanation,
        option_rationales=rationales,
        knowledge_point=knowledge_point,
        difficulty=difficulty,
        source_type="ai_generated",
        source_name="fallback",
        source_year=None,
    )


def _canonical_subject_key(topic_name: str) -> str:
    compact = topic_name.replace(" ", "")
    lowered = topic_name.lower()
    if any(term in compact for term in ("数据结构与算法", "数据结构", "数据与结构", "算法")):
        return "data-structure"
    if any(term in compact for term in ("计算机网络", "网络原理", "计网")):
        return "computer-network"
    if any(term in compact for term in ("计算机组成原理", "计算机组成", "组成原理", "计组")):
        return "computer-organization"
    if any(term in compact for term in ("操作系统原理", "操作系统")) or lowered == "os":
        return "operating-system"
    return ""


def build_mixed_practice_items_with_status(
    *,
    subject_id: str,
    subject_name: str,
    topic: str,
    difficulty: str,
    count: int,
    original_question: str,
    user_style_name: str,
    user_style_prompt: str,
    short_term_context: str,
    session_memory_context: str,
    long_term_context: str,
    model_name: str | None = None,
    rag_context: str = "（本轮未检索到额外知识库材料）",
    knowledge_points: list[str] | None = None,
) -> PracticeGenerationResult:
    requested_count = max(1, count)
    effective_points = [point for point in list(knowledge_points or []) if str(point).strip()]
    if not effective_points:
        effective_points = [topic]
    bank_candidates = _list_question_bank_items(
        subject_id=subject_id,
        knowledge_points=effective_points,
        difficulty=difficulty,
        limit=requested_count * 2,
    )

    if len(bank_candidates) < requested_count:
        fallback_candidates = _list_question_bank_items(
            subject_id=subject_id,
            knowledge_points=effective_points,
            limit=requested_count * 3,
        )
        bank_candidates = dedupe_quiz_items([*bank_candidates, *fallback_candidates])

    picked = bank_candidates[:requested_count]
    if len(picked) >= requested_count:
        items = [normalize_quiz_item(item) for item in picked[:requested_count]]
        return PracticeGenerationResult(
            items=[PracticeRecommendation.model_validate(item) for item in items],
            status={
                "requested_count": requested_count,
                "generated_count": len(items),
                "question_bank_count": len(items),
                "ai_count": 0,
                "fallback_count": 0,
                "partial": False,
                "degraded_reason": "",
            },
        )

    missing_count = requested_count - len(picked)
    user_style_instruction = format_user_style_instruction(user_style_name, user_style_prompt)
    degraded_reason = ""

    try:
        generated = _invoke_generation_chain(
            {
                "count": missing_count,
                "topic": topic,
                "difficulty": difficulty,
                "subject_name": subject_name,
                "user_style_instruction": user_style_instruction,
                "short_term_context": short_term_context,
                "session_memory_context": session_memory_context,
                "long_term_context": long_term_context,
                "rag_context": rag_context or "（本轮未检索到额外知识库材料）",
                "original_question": original_question or "（无原始问题）",
            },
            model_name=model_name,
        )
        generated_items = [
            normalize_quiz_item(
                {
                    **item.model_dump(),
                    "question_id": f"ai-{uuid.uuid4()}",
                    "source_type": "ai_generated",
                    "source_name": "",
                    "source_year": None,
                }
            )
            for item in generated.items[:missing_count]
        ]
    except Exception as exc:
        logger.error(f"❌ AI 选择题生成失败: {exc}")
        degraded_reason = f"AI 选择题生成失败: {exc}"
        generated_items = []

    normalized_picked = [normalize_quiz_item(item) for item in picked]
    deduped_items = dedupe_quiz_items([*normalized_picked, *generated_items])
    fallback_count = 0
    attempt = 0
    while len(deduped_items) < requested_count and attempt < requested_count * 4:
        fallback_item = _build_fallback_practice_item(
            topic=topic,
            subject_name=subject_name,
            difficulty=difficulty,
            index=attempt,
        )
        previous_count = len(deduped_items)
        deduped_items = dedupe_quiz_items([*deduped_items, fallback_item])
        if len(deduped_items) > previous_count:
            fallback_count += 1
        attempt += 1

    final_items = [PracticeRecommendation.model_validate(item) for item in deduped_items[:requested_count]]
    if fallback_count and not degraded_reason:
        degraded_reason = "AI 选择题不足，已用备用题补齐。"

    return PracticeGenerationResult(
        items=final_items,
        status={
            "requested_count": requested_count,
            "generated_count": len(final_items),
            "question_bank_count": len(normalized_picked),
            "ai_count": len(generated_items),
            "fallback_count": fallback_count,
            "partial": len(final_items) < requested_count,
            "degraded_reason": degraded_reason,
        },
    )


def build_mixed_practice_items(
    **kwargs: Any,
) -> list[PracticeRecommendation]:
    return build_mixed_practice_items_with_status(**kwargs).items


def build_recommended_practice_items(
    *,
    user_id: str,
    subject_id: str | None,
    subject_name: str,
    user_style_name: str,
    user_style_prompt: str,
    short_term_context: str = "（暂无短期上下文）",
    session_memory_context: str = "（暂无会话摘要）",
    long_term_context: str = "（暂无长期学习记忆）",
    limit: int = 4,
    model_name: str | None = None,
) -> list[PracticeRecommendation]:
    recommended = _list_practice_recommendations(
        user_id,
        subject_id=subject_id,
        limit=limit,
    )
    if len(recommended) >= limit:
        return [PracticeRecommendation.model_validate(item) for item in recommended[:limit]]

    memory = _get_user_memory(user_id)
    focus_topic = (
        next(iter(memory.get("weak_points", []) or []), "")
        or next(iter(memory.get("recent_topics", []) or []), "")
        or "综合"
    )
    difficulty = determine_difficulty(focus_topic, dict(memory.get("error_count", {}) or {}))

    ai_items = build_mixed_practice_items(
        subject_id=subject_id or "general",
        subject_name=subject_name,
        topic=focus_topic,
        difficulty=difficulty,
        count=max(1, limit - len(recommended)),
        original_question=f"推荐围绕「{focus_topic}」的练习题",
        user_style_name=user_style_name,
        user_style_prompt=user_style_prompt,
        short_term_context=short_term_context,
        session_memory_context=session_memory_context,
        long_term_context=long_term_context,
        model_name=model_name,
        knowledge_points=[focus_topic],
    )
    deduped_items = dedupe_quiz_items([
        *[normalize_quiz_item(item) for item in recommended],
        *ai_items,
    ])
    return [PracticeRecommendation.model_validate(item) for item in deduped_items[:limit]]
