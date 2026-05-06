from __future__ import annotations

import re
from typing import Any

from app.shared.schemas.contracts import (
    PracticeRecommendation,
    QuizClarificationPanel,
    QuizRecommendedOption,
    QuizRequestResolution,
)
from app.shared.schemas.subject import DEFAULT_SUBJECTS


QUIZ_INTENT_TERMS = (
    "出题",
    "刷题",
    "练习",
    "考我",
    "测试我",
    "来几道题",
    "再来几题",
    "再出一些题",
    "继续出题",
    "帮我巩固一下",
    "给我做题",
    "ai补题",
    "AI补题",
    "补题",
)
CONTINUATION_TERMS = ("再", "继续", "还有吗", "换几道", "难一点", "简单一点", "再来")
CURRENT_CONTEXT_TERMS = ("当前问题", "刚才这个", "这道题相关", "这道题", "当前题")
WEAK_POINT_TERMS = ("错题", "薄弱点", "不会的地方", "薄弱", "错的")
GENERIC_SUBJECT_SUFFIX_TERMS = {
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
    "题目",
    "题",
    "练习",
    "测验",
    "测试",
}

CANONICAL_SUBJECT_ALIASES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "data-structure",
        "数据结构与算法",
        (
            "数据结构与算法",
            "数据结构",
            "数据与结构",
            "数据结构类型",
            "数据与结构类型",
            "算法",
        ),
    ),
    ("computer-network", "计算机网络", ("计算机网络", "网络原理", "计网")),
    (
        "computer-organization",
        "计算机组成原理",
        ("计算机组成原理", "计算机组成", "组成原理", "计组"),
    ),
    ("operating-system", "操作系统原理", ("操作系统原理", "操作系统", "OS", "os")),
)
SUBJECT_NAME_BY_ID = {str(item["id"]): str(item["name"]) for item in DEFAULT_SUBJECTS}


def resolve_quiz_request(user_input: str, context: dict[str, Any] | None = None) -> QuizRequestResolution:
    """Resolve whether a user message should create or clarify a practice pack."""

    context = dict(context or {})
    message = " ".join(str(user_input or "").split()).strip()
    previous_topic = _previous_topic(context)
    if not _has_quiz_intent(message, context):
        return QuizRequestResolution(
            is_quiz_request=False,
            action="normal_qa",
            intent="normal_qa",
            topic=None,
            previous_topic=previous_topic,
            source="unknown",
            question_type="unknown",
            difficulty="unknown",
            count=None,
            target_module="qa",
            reason="no_quiz_generation_signal",
        )

    question_type = _parse_question_type(message)
    count = _parse_count(message)
    difficulty = _parse_difficulty(message, context)
    explicit_topic, explicit_subject_id = _extract_explicit_topic(message)
    if explicit_topic:
        return _generate_resolution(
            topic=explicit_topic,
            subject_id=explicit_subject_id,
            source="explicit_user_input",
            previous_topic=previous_topic,
            message=message,
            question_type=question_type,
            difficulty=difficulty,
            count=count,
            reason="explicit_topic_in_user_input",
        )

    context_topic, context_source = _topic_from_current_context(message, context)
    if context_topic:
        return _generate_resolution(
            topic=context_topic,
            source=context_source,
            previous_topic=previous_topic,
            message=message,
            question_type=question_type,
            difficulty=difficulty,
            count=count,
            reason=f"inherited_topic_from_{context_source}",
        )

    if _mentions_weak_points(message):
        weak_points = _string_list(context.get("weak_points"))
        if weak_points:
            return _generate_resolution(
                topic=weak_points[0],
                source="weak_point",
                previous_topic=previous_topic,
                message=message,
                question_type=question_type,
                difficulty=difficulty,
                count=count,
                reason="weak_point_requested",
            )

    recommended = _recommended_options(context)
    return QuizRequestResolution(
        is_quiz_request=True,
        action="clarify_quiz_request",
        intent="quiz_generation",
        topic=None,
        previous_topic=previous_topic,
        source="unknown",
        question_type=question_type,
        difficulty=difficulty,
        count=count,
        target_module="practice",
        need_clarification=True,
        clarification_reason="missing_topic",
        recommended_options=recommended,
        custom_input_placeholder=_custom_placeholder(),
        reason="quiz_intent_without_usable_topic",
    )


def build_quiz_clarification_panel(resolution: QuizRequestResolution) -> QuizClarificationPanel:
    return QuizClarificationPanel(
        recommended_options=resolution.recommended_options or _default_recommendations(),
        question_type_options=[
            QuizRecommendedOption(label="单选题", value="single_choice", source="default"),
            QuizRecommendedOption(label="多选题（待扩展）", value="multiple_choice", source="default"),
            QuizRecommendedOption(label="判断题（待扩展）", value="true_false", source="default"),
            QuizRecommendedOption(label="简答题（待扩展）", value="short_answer", source="default"),
        ],
        difficulty_options=[
            QuizRecommendedOption(label="简单", value="easy", source="default"),
            QuizRecommendedOption(label="中等", value="medium", source="default"),
            QuizRecommendedOption(label="困难", value="hard", source="default"),
            QuizRecommendedOption(label="自适应", value="adaptive", source="default"),
        ],
        count_options=[
            QuizRecommendedOption(label="3 道", value="3", source="default"),
            QuizRecommendedOption(label="5 道", value="5", source="default"),
            QuizRecommendedOption(label="8 道", value="8", source="default"),
        ],
        custom_input_placeholder=resolution.custom_input_placeholder or _custom_placeholder(),
    )


def context_from_practice_question(
    *,
    current_practice_question: dict[str, Any] | PracticeRecommendation | None = None,
    last_practice_pack: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = dict(extra or {})
    if isinstance(current_practice_question, PracticeRecommendation):
        current_payload = current_practice_question.model_dump()
    elif isinstance(current_practice_question, dict):
        current_payload = dict(current_practice_question)
    else:
        current_payload = {}
    if current_payload:
        context["current_practice_question"] = current_payload
        if current_payload.get("knowledge_point"):
            context.setdefault("current_question_topic", current_payload.get("knowledge_point"))
    if last_practice_pack:
        context["last_practice_pack"] = list(last_practice_pack)
        first = last_practice_pack[0] if isinstance(last_practice_pack[0], dict) else {}
        if isinstance(first, dict) and first.get("knowledge_point"):
            context.setdefault("last_topic", first.get("knowledge_point"))
    return context


def _has_quiz_intent(message: str, context: dict[str, Any]) -> bool:
    lowered = message.lower()
    if any(term in message or term.lower() in lowered for term in QUIZ_INTENT_TERMS):
        return True
    if re.search(r"(出|来|生成|做|练|考|测试).{0,12}(题|练习|测验)", message):
        return True
    if "做题" in message:
        return True
    if any(term in message for term in CONTINUATION_TERMS):
        return bool(
            context.get("last_topic")
            or context.get("current_question")
            or context.get("current_practice_question")
            or context.get("last_practice_pack")
        )
    return False


def _generate_resolution(
    *,
    topic: str,
    subject_id: str | None = None,
    source: str,
    previous_topic: str | None,
    message: str,
    question_type: str,
    difficulty: str,
    count: int,
    reason: str,
) -> QuizRequestResolution:
    intent = "continue_quiz_generation" if any(term in message for term in CONTINUATION_TERMS) else "quiz_generation"
    active_topic = topic.strip() if topic else None
    requested_topic = active_topic if source != "last_topic" else None
    should_switch_topic = bool(
        requested_topic
        and previous_topic
        and _normalize_topic_for_compare(requested_topic) != _normalize_topic_for_compare(previous_topic)
    )
    topic_resolution_reason = (
        f"explicit_or_context_topic_overrides_previous:{previous_topic}->{requested_topic}"
        if should_switch_topic
        else (
            "inherited_previous_topic"
            if source == "last_topic"
            else "resolved_topic_from_current_request"
        )
    )
    return QuizRequestResolution(
        is_quiz_request=True,
        action="generate_practice_pack",
        intent=intent,
        topic=topic,
        subject_id=subject_id,
        requested_topic=requested_topic,
        previous_topic=previous_topic,
        active_topic=active_topic,
        should_switch_topic=should_switch_topic,
        topic_resolution_reason=topic_resolution_reason,
        source=source,  # type: ignore[arg-type]
        question_type=question_type,  # type: ignore[arg-type]
        difficulty=difficulty,  # type: ignore[arg-type]
        count=count,
        target_module="practice",
        need_clarification=False,
        clarification_reason=None,
        recommended_options=[],
        custom_input_placeholder=None,
        reason=reason,
    )


def _previous_topic(context: dict[str, Any]) -> str | None:
    topic = str(context.get("last_topic") or "").strip()
    if topic:
        return topic
    recent_topics = _string_list(context.get("recent_topics"))
    return recent_topics[0] if recent_topics else None


def _normalize_topic_for_compare(topic: str) -> str:
    return re.sub(r"\s+", "", topic).strip().lower()


def _parse_question_type(message: str) -> str:
    if "多选" in message:
        return "multiple_choice"
    if "判断" in message or "判断题" in message:
        return "true_false"
    if "简答" in message or "问答题" in message:
        return "short_answer"
    if "混合" in message or "综合题型" in message:
        return "mixed"
    return "single_choice"


def _parse_count(message: str) -> int:
    match = re.search(r"(\d+)\s*道", message)
    if match:
        return max(1, min(10, int(match.group(1))))
    zh_counts = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    match = re.search(r"([一两二三四五六七八九十])\s*道", message)
    if match:
        return zh_counts.get(match.group(1), 5)
    return 5


def _parse_difficulty(message: str, context: dict[str, Any]) -> str:
    if any(term in message for term in ("挑战", "难一点", "困难", "hard")):
        return "hard"
    if any(term in message for term in ("中等", "面试", "medium")):
        return "medium"
    if any(term in message for term in ("简单", "基础", "新手", "easy")):
        return "easy"
    learner_stage = str(context.get("learner_stage") or context.get("learning_stage") or "").lower()
    training_mode = str(context.get("training_mode") or context.get("scenario") or "").lower()
    if "new" in learner_stage or "新手" in learner_stage:
        return "easy"
    if "interview" in training_mode or "面试" in training_mode:
        return "medium"
    return "adaptive"


def _extract_explicit_topic(message: str) -> tuple[str, str | None]:
    subject_topic, subject_id = _extract_explicit_subject_topic(message)
    if subject_topic:
        return subject_topic, subject_id

    patterns = [
        r"(?:围绕|关于|针对|基于)\s*(.+?)\s*(?:出|来|生成|做|练|考|测试)",
        r"(?:出|来|生成|给我来)\s*\d*\s*道?\s*([A-Za-z][A-Za-z0-9_/#.+-]*)\s*(?:单选|多选|判断|简答|题)",
        r"(?:出|来|生成|给我来)\s*(?:几|一些|点)?\s*道?\s*([A-Za-z][A-Za-z0-9_/#.+-]*)\s*(?:的)?(?:中等|简单|困难|基础|难一点)?(?:难度)?题",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        topic = _clean_topic(match.group(1))
        if topic:
            return topic, _subject_id_for_topic(topic)

    english_terms = [
        term
        for term in re.findall(r"[A-Za-z][A-Za-z0-9_/#.+-]*", message)
        if term.lower() not in {"ai", "easy", "medium", "hard"}
    ]
    if english_terms and any(term in message for term in QUIZ_INTENT_TERMS):
        topic = english_terms[-1][:60]
        return topic, _subject_id_for_topic(topic)
    return "", None


def _extract_explicit_subject_topic(message: str) -> tuple[str, str | None]:
    compact_message = re.sub(r"\s+", "", message)
    for subject_id, subject_name, aliases in CANONICAL_SUBJECT_ALIASES:
        matched_alias = next((alias for alias in aliases if alias and alias in compact_message), "")
        if not matched_alias:
            continue

        subtopic = _subject_subtopic_after_alias(compact_message, matched_alias)
        if subtopic:
            return subtopic, subject_id
        return SUBJECT_NAME_BY_ID.get(subject_id, subject_name), subject_id
    return "", None


def _subject_subtopic_after_alias(message: str, alias: str) -> str:
    """Extract a specific subtopic from phrases like 数据结构与算法里的栈和队列题."""

    suffix = message.split(alias, 1)[1]
    suffix = re.sub(
        r"^(有关的|有关|相关的|相关|类型|方向|方面|知识库|学科|课程|里|里面|中的|中|关于|围绕|的)+",
        "",
        suffix,
    )
    match = re.search(r"(.{1,30}?)(?:题目|题|练习|测验|测试)", suffix)
    if not match:
        return ""
    topic = _clean_topic(match.group(1))
    if _is_generic_subject_subtopic(topic):
        return ""
    return topic


def _is_generic_subject_subtopic(topic: str) -> bool:
    compact_topic = re.sub(r"\s+", "", topic).strip("：:，,。.!！?？的")
    return compact_topic in GENERIC_SUBJECT_SUFFIX_TERMS


def _subject_id_for_topic(topic: str) -> str | None:
    compact_topic = re.sub(r"\s+", "", topic)
    for subject_id, _, aliases in CANONICAL_SUBJECT_ALIASES:
        if any(alias and alias in compact_topic for alias in aliases):
            return subject_id
    return None


def _topic_from_current_context(message: str, context: dict[str, Any]) -> tuple[str, str]:
    if any(term in message for term in CURRENT_CONTEXT_TERMS):
        topic = _context_question_topic(context.get("current_question")) or _context_question_topic(
            context.get("current_practice_question")
        )
        if topic:
            return topic, "current_question"

    current_practice = _context_question_topic(context.get("current_practice_question"))
    if "AI补题" in message or "ai补题" in message.lower() or "补题" in message:
        if current_practice:
            return current_practice, "current_question"
    current_topic = _context_question_topic(context.get("current_question")) or current_practice
    if current_topic:
        return current_topic, "current_question"

    last_pack_topic = _context_question_topic(context.get("last_practice_pack"))
    if last_pack_topic:
        return last_pack_topic, "last_topic"

    last_topic = str(context.get("last_topic") or "").strip()
    if last_topic:
        return last_topic, "last_topic"

    if any(term in message for term in CONTINUATION_TERMS):
        return "", "unknown"

    return "", "unknown"


def _context_question_topic(value: Any) -> str:
    if isinstance(value, PracticeRecommendation):
        return value.knowledge_point.strip() or _clean_topic(value.question)
    if isinstance(value, dict):
        for key in ("knowledge_point", "topic", "concept", "concept_name", "title"):
            topic = str(value.get(key) or "").strip()
            if topic:
                return topic[:60]
        return _clean_topic(str(value.get("question") or value.get("content") or ""))
    if isinstance(value, list) and value:
        return _context_question_topic(value[0])
    text = str(value or "").strip()
    return _clean_topic(text) if text else ""


def _mentions_weak_points(message: str) -> bool:
    return any(term in message for term in WEAK_POINT_TERMS)


def _recommended_options(context: dict[str, Any]) -> list[QuizRecommendedOption]:
    options: list[QuizRecommendedOption] = []
    current = _context_question_topic(context.get("current_practice_question") or context.get("current_question"))
    if current:
        options.append(QuizRecommendedOption(label=f"围绕当前内容：{current}", value=current, source="current_context"))
    for topic in _string_list(context.get("weak_points"))[:3]:
        options.append(QuizRecommendedOption(label=f"错题强化：{topic}", value=topic, source="weak_point"))
    for topic in _string_list(context.get("recent_topics"))[:3]:
        options.append(QuizRecommendedOption(label=f"最近学习：{topic}", value=topic, source="recent_topic"))
    if not options:
        options = _default_recommendations()
    seen: set[str] = set()
    deduped: list[QuizRecommendedOption] = []
    for option in options:
        if option.value in seen:
            continue
        seen.add(option.value)
        deduped.append(option)
    return deduped[:6]


def _default_recommendations() -> list[QuizRecommendedOption]:
    return [
        QuizRecommendedOption(label="输入一个想练的知识点", value="custom_topic", source="default"),
        QuizRecommendedOption(label="选择最近学习内容", value="recent_topic", source="default"),
        QuizRecommendedOption(label="选择错题强化方向", value="weak_point", source="default"),
    ]


def _custom_placeholder() -> str:
    return "例如：围绕 HashMap 出 5 道单选题"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clean_topic(value: str) -> str:
    topic = re.sub(
        r"(帮我|请|给我|来|出|生成|做|练习|刷题|题目|题|单选题|多选题|判断题|简答题|难度|中等|简单|困难|基础|几道|一些|点)",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    topic = re.sub(r"\s+", " ", topic).strip(" ：:，,。.!！?？「」『』")
    return topic[:60]
