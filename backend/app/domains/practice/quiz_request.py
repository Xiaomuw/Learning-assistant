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
    "来一组",
    "做一套",
    "小测一下",
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
ENGLISH_QUIZ_INTENT_TERMS = (
    "practice question",
    "practice questions",
    "quiz me",
    "question pack",
    "generate question",
    "generate questions",
    "create question",
    "create questions",
    "make question",
    "make questions",
    "multiple choice",
    "mcq",
    "mcqs",
    "test me",
    "drill me",
)
CONTINUATION_TERMS = ("再", "继续", "还有吗", "换几道", "难一点", "简单一点", "再来", "more", "again", "another", "continue")
CURRENT_CONTEXT_TERMS = ("当前问题", "刚才这个", "这道题相关", "这道题", "当前题")
WEAK_POINT_TERMS = ("错题", "薄弱点", "不会的地方", "薄弱", "错的", "弱项", "短板")
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
    "单选",
    "单选题",
    "选择题",
    "多选",
    "多选题",
    "判断",
    "判断题",
    "简答",
    "简答题",
    "问答",
    "问答题",
    "练习",
    "练习题",
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
        if not _is_supported_generation_question_type(question_type):
            return _unsupported_question_type_resolution(
                topic=explicit_topic,
                subject_id=explicit_subject_id,
                source="explicit_user_input",
                previous_topic=previous_topic,
                question_type=question_type,
                difficulty=difficulty,
                count=count,
            )
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

    if _mentions_weak_points(message):
        weak_points = _string_list(context.get("weak_points"))
        if weak_points:
            if not _is_supported_generation_question_type(question_type):
                return _unsupported_question_type_resolution(
                    topic=weak_points[0],
                    source="weak_point",
                    previous_topic=previous_topic,
                    question_type=question_type,
                    difficulty=difficulty,
                    count=count,
                )
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

    context_topic, context_source = _topic_from_current_context(message, context)
    if context_topic:
        if not _is_supported_generation_question_type(question_type):
            return _unsupported_question_type_resolution(
                topic=context_topic,
                source=context_source,
                previous_topic=previous_topic,
                question_type=question_type,
                difficulty=difficulty,
                count=count,
            )
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

    recommended = _recommended_options(context)
    unsupported_question_type = not _is_supported_generation_question_type(question_type)
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
        clarification_reason="unsupported_question_type" if unsupported_question_type else "missing_topic",
        recommended_options=recommended,
        custom_input_placeholder=_custom_placeholder(),
        reason="unsupported_question_type" if unsupported_question_type else "quiz_intent_without_usable_topic",
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
    if _is_question_construction_explanation(message):
        return False
    if any(term in message or term.lower() in lowered for term in QUIZ_INTENT_TERMS):
        return True
    if any(term in lowered for term in ENGLISH_QUIZ_INTENT_TERMS):
        return True
    if re.search(
        r"\b(?:generate|create|make|write|build|give me)\b.{0,40}\b(?:questions?|quizzes|mcqs?)\b",
        lowered,
    ):
        return True
    if re.search(r"(出|来|生成|做|练|考|测试).{0,30}(题|练习|测验|单选|选择)", message):
        return True
    if re.search(r"(?:围绕|关于|针对|有关).{1,40}(?:出|生成|做|练|考|测试|题|练习|测验|单选|选择)", message):
        return True
    if "做题" in message:
        return True
    if _has_continuation_signal(message) and re.search(r"(?:题|道|练习|测验|单选|选择)", message):
        return True
    if _has_continuation_signal(message):
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
    intent = "continue_quiz_generation" if _has_continuation_signal(message) else "quiz_generation"
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


def _unsupported_question_type_resolution(
    *,
    topic: str | None,
    subject_id: str | None = None,
    source: str,
    previous_topic: str | None,
    question_type: str,
    difficulty: str,
    count: int,
) -> QuizRequestResolution:
    return QuizRequestResolution(
        is_quiz_request=True,
        action="clarify_quiz_request",
        intent="quiz_generation",
        topic=topic,
        subject_id=subject_id,
        requested_topic=topic,
        previous_topic=previous_topic,
        active_topic=topic,
        source=source,  # type: ignore[arg-type]
        question_type=question_type,  # type: ignore[arg-type]
        difficulty=difficulty,  # type: ignore[arg-type]
        count=count,
        target_module="practice",
        need_clarification=True,
        clarification_reason="unsupported_question_type",
        recommended_options=_default_recommendations(),
        custom_input_placeholder=_custom_placeholder(),
        reason="unsupported_question_type",
    )


def _is_supported_generation_question_type(question_type: str) -> bool:
    return question_type in {"single_choice", "unknown", ""}


def _previous_topic(context: dict[str, Any]) -> str | None:
    topic = str(context.get("last_topic") or "").strip()
    if topic:
        return topic
    recent_topics = _string_list(context.get("recent_topics"))
    return recent_topics[0] if recent_topics else None


def _normalize_topic_for_compare(topic: str) -> str:
    return re.sub(r"\s+", "", topic).strip().lower()


def _has_continuation_signal(message: str) -> bool:
    lowered = message.lower()
    return any(term in message or term in lowered for term in CONTINUATION_TERMS)


def _parse_question_type(message: str) -> str:
    lowered = message.lower()
    if "多选" in message:
        return "multiple_choice"
    if "multi-select" in lowered or "multiple answer" in lowered:
        return "multiple_choice"
    if "判断" in message or "判断题" in message:
        return "true_false"
    if "true false" in lowered or "true/false" in lowered:
        return "true_false"
    if "简答" in message or "问答题" in message:
        return "short_answer"
    if "short answer" in lowered:
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
    lowered = message.lower()
    english_counts = {
        "one": 1,
        "a": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    match = re.search(r"\b(\d+)\s*(?:practice\s*)?(?:questions?|quizzes|mcqs?|items)\b", lowered)
    if match:
        return max(1, min(10, int(match.group(1))))
    match = re.search(
        r"\b(one|a|two|three|four|five|six|seven|eight|nine|ten)\s*(?:practice\s*)?(?:questions?|quizzes|mcqs?|items)\b",
        lowered,
    )
    if match:
        return english_counts.get(match.group(1), 5)
    match = re.search(
        r"\b(?:generate|create|make|write|build|give me)\s+(\d+|one|a|two|three|four|five|six|seven|eight|nine|ten)\b",
        lowered,
    )
    if match:
        raw_count = match.group(1)
        if raw_count.isdigit():
            return max(1, min(10, int(raw_count)))
        return english_counts.get(raw_count, 5)
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
    """Extract an explicit requested quiz topic from the current message.

    The resolver must treat an explicit topic in the user's latest request as
    stronger than stale session context. Keep this parser deterministic and
    conservative: it only returns a topic when quiz-intent scaffolding can be
    removed cleanly.
    """

    normalized = _strip_followup_instruction(message)
    english_topic = _extract_english_topic(normalized)
    if english_topic:
        return english_topic, _subject_id_for_topic(english_topic)

    normalized = _remove_count_and_type_terms(normalized)
    if _is_context_only_topic_candidate(normalized) or _mentions_weak_points(normalized):
        return "", None

    subject_topic, subject_id = _extract_subject_alias_topic(normalized)
    if subject_id:
        subject_subtopic = _extract_subtopic_after_subject_alias(normalized)
        if subject_subtopic:
            return subject_subtopic, subject_id
        return subject_topic, subject_id

    specific_topic = _extract_chinese_specific_topic(normalized)
    if specific_topic:
        return specific_topic, _subject_id_for_topic(specific_topic)

    generic_topic = _extract_chinese_generic_topic(normalized)
    if generic_topic:
        return generic_topic, _subject_id_for_topic(generic_topic)
    return "", None


def _strip_followup_instruction(message: str) -> str:
    first_line = str(message or "").replace("\r", "\n").split("\n", 1)[0]
    return " ".join(first_line.split()).strip()


def _remove_count_and_type_terms(message: str) -> str:
    cleaned = str(message or "")
    cleaned = re.sub(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:几|若干|一些)\s*(?:道|题)", " ", cleaned)
    cleaned = re.sub(r"[一两二三四五六七八九十0-9]+\s*道", " ", cleaned)
    cleaned = re.sub(r"(?:单选题|单选|选择题|选择|多选题|多选|判断题|判断|简答题|简答|问答题|问答|题目|练习题|题|练习)", " ", cleaned)
    return " ".join(cleaned.split()).strip()


def _extract_english_topic(message: str) -> str:
    patterns = (
        r"\b(?:quiz me|test me|drill me)\s+(?:on|about)?\s*([A-Za-z][A-Za-z0-9+#._/-]*(?:\s+[A-Za-z][A-Za-z0-9+#._/-]*){0,3})\b",
        r"\b(?:generate|create|make|write|build|give me)\b.*?\b(?:about|on|for)\s+([A-Za-z][A-Za-z0-9+#._/-]*(?:\s+[A-Za-z][A-Za-z0-9+#._/-]*){0,3})\b",
        r"\b(?:generate|create|make|write|build)\b\s+([A-Za-z][A-Za-z0-9+#._/-]*(?:\s+[A-Za-z][A-Za-z0-9+#._/-]*){0,3})\s+(?:practice|quiz|mcq|question)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        topic = _clean_extracted_topic(match.group(1))
        topic = re.sub(r"\b(?:practice|quiz|questions?|mcqs?|multiple choice|single choice)\b", "", topic, flags=re.IGNORECASE)
        topic = _clean_extracted_topic(topic)
        if topic:
            return topic
    return ""


def _extract_subject_alias_topic(message: str) -> tuple[str, str | None]:
    compact = _normalize_topic_for_compare(message)
    for subject_id, subject_name, aliases in CANONICAL_SUBJECT_ALIASES:
        for alias in sorted(aliases, key=len, reverse=True):
            alias_compact = _normalize_topic_for_compare(alias)
            if not alias_compact or alias_compact not in compact:
                continue
            tail = compact.split(alias_compact, 1)[1]
            if tail in GENERIC_SUBJECT_SUFFIX_TERMS or all(term in GENERIC_SUBJECT_SUFFIX_TERMS for term in _split_generic_tail(tail)):
                return subject_name, subject_id
            return subject_name, subject_id
    return "", None



def _is_context_only_topic_candidate(message: str) -> bool:
    compact = _normalize_topic_for_compare(message)
    context_only = {
        "ai补",
        "AI补",
        "帮我再出一些",
        "帮我再出",
        "再出一些",
        "再出",
        "再来",
        "继续出",
        "继续",
        "帮我出点",
        "出点",
        "帮我出",
        "给我出",
        "请出",
    }
    if compact in {_normalize_topic_for_compare(item) for item in context_only}:
        return True
    return not compact or compact in GENERIC_SUBJECT_SUFFIX_TERMS


def _extract_subtopic_after_subject_alias(message: str) -> str:
    for _subject_id, _subject_name, aliases in CANONICAL_SUBJECT_ALIASES:
        for alias in sorted(aliases, key=len, reverse=True):
            if alias not in message:
                continue
            tail = message.split(alias, 1)[1]
            tail = _clean_extracted_topic(tail)
            tail = re.sub(r"^(?:里|里的|中|中的|有关|相关|类型|方向|方面|的)+", "", tail)
            tail = re.sub(r"(?:给我|帮我|请|出|生成|来|做|考|测试|刷)+$", "", tail)
            tail = _clean_extracted_topic(tail)
            if not tail or _is_generic_topic_name(tail):
                return ""
            return tail
    return ""

def _extract_chinese_specific_topic(message: str) -> str:
    patterns = (
        r"(?:围绕|关于|针对|有关)\s*[「『《“\"]?([^」』》”，，。！？,.!?：:]{1,40}?)[」』》”\"]?\s*(?:出|生成|来|做|考|测试|刷|练|$)",
        r"(?:围绕|关于|针对|有关)\s*([^，。！？,.!?：:]{1,40})",
        r"(?:出|生成|来|做|考|测试|刷)\s*(?:一些|几道|点)?\s*([^，。！？,.!?：:]{1,40})",
        r"(?:帮我|给我|请)?\s*([^，。！？,.!?：:]{1,40}?)(?:相关|有关)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, message)
        if not match:
            continue
        topic = _clean_extracted_topic(match.group(1))
        topic = _remove_subject_container_terms(topic)
        if topic and not _is_generic_topic_name(topic):
            return topic
    return ""


def _extract_chinese_generic_topic(message: str) -> str:
    topic = _clean_extracted_topic(message)
    topic = _remove_subject_container_terms(topic)
    if topic and not _is_generic_topic_name(topic):
        return topic
    return ""


def _split_generic_tail(tail: str) -> list[str]:
    if not tail:
        return []
    return [item for item in re.split(r"(?:的|有关|相关|类型|方向|方面)", tail) if item]


def _remove_subject_container_terms(topic: str) -> str:
    cleaned = str(topic or "")
    cleaned = re.sub(r"^(?:有关|关于|围绕|针对|一些|几道|点|的|和|里|里的|类型|方向|方面)+", "", cleaned)
    cleaned = re.sub(r"(?:相关|有关|类型|方向|方面|知识库|课程|学科|的|里|里的)+$", "", cleaned)
    for _subject_id, _subject_name, aliases in CANONICAL_SUBJECT_ALIASES:
        for alias in sorted(aliases, key=len, reverse=True):
            cleaned = cleaned.replace(f"{alias}里的", "")
            cleaned = cleaned.replace(f"{alias}里", "")
            cleaned = cleaned.replace(alias, "") if cleaned != alias else cleaned
    return _clean_extracted_topic(cleaned)


def _clean_extracted_topic(topic: str) -> str:
    cleaned = str(topic or "")
    cleaned = re.sub(r"(?:请只给.*|只给.*|不要.*|并且.*)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|a|an|\d+)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:408\s*风格|408|考研风格|真题风格|风格)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:单选|选择|多选|判断|简答|问答|practice|quiz|mcq|question|questions)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*(?:出|生成|来|做|考|测试|刷)?\s*道$", "", cleaned)
    cleaned = re.sub(r"(?:\s|^)(?:出|生成|来|做|考|测试|刷|给我|帮我|请)+$", "", cleaned)
    cleaned = re.sub(r"(?:类型|方向|方面|有关|相关|的|里|里的|给我)+$", "", cleaned)
    cleaned = cleaned.strip(" 「」『』《》“”\"'：:，,。.!！?？、；;\t\n\r")
    return " ".join(cleaned.split()).strip()


def _subject_id_for_topic(topic: str) -> str | None:
    compact = _normalize_topic_for_compare(topic)
    for subject_id, _subject_name, aliases in CANONICAL_SUBJECT_ALIASES:
        if any(_normalize_topic_for_compare(alias) in compact for alias in aliases):
            return subject_id
    if any(term in compact for term in ("stack", "栈", "队列", "数组", "链表", "哈希", "hashmap", "数据库索引", "索引")):
        return "data-structure"
    if any(term in compact for term in ("http", "https", "tcp", "udp", "dns", "ip", "端口", "路由")):
        return "computer-network"
    if any(term in compact for term in ("cpu", "alu", "cache", "寄存器", "指令", "流水线", "总线", "存储器", "补码", "中断")):
        return "computer-organization"
    if any(term in compact for term in ("进程", "线程", "调度", "死锁", "虚拟内存", "内存管理", "文件系统", "系统调用", "同步", "互斥", "信号量")):
        return "operating-system"
    return None


def _is_generic_topic_name(topic: str) -> bool:
    compact = _normalize_topic_for_compare(topic)
    if compact in GENERIC_SUBJECT_SUFFIX_TERMS:
        return True
    return not bool(compact)

def _topic_from_current_context(message: str, context: dict[str, Any]) -> tuple[str, str]:
    if any(term in message for term in CURRENT_CONTEXT_TERMS):
        topic = _context_question_topic(context.get("current_question")) or _context_question_topic(
            context.get("current_practice_question")
        )
        if topic:
            return topic, "current_question"

    if "AI补题" in message or "ai补题" in message.lower() or "补题" in message:
        current_practice_explicit = _context_explicit_topic(context.get("current_practice_question"))
        if current_practice_explicit:
            return current_practice_explicit, "current_question"
        for key in ("current_question_topic", "topic", "active_topic"):
            context_topic = str(context.get(key) or "").strip()
            if context_topic:
                return context_topic[:60], "last_topic"
    current_practice = _context_question_topic(context.get("current_practice_question"))
    current_topic = _context_question_topic(context.get("current_question")) or current_practice
    if current_topic:
        return current_topic, "current_question"

    for key in ("current_question_topic", "topic", "active_topic"):
        context_topic = str(context.get(key) or "").strip()
        if context_topic:
            return context_topic[:60], "last_topic"

    last_pack_topic = _context_question_topic(context.get("last_practice_pack"))
    if last_pack_topic:
        return last_pack_topic, "last_topic"

    last_topic = str(context.get("last_topic") or "").strip()
    if last_topic:
        return last_topic, "last_topic"

    if _has_continuation_signal(message):
        return "", "unknown"

    return "", "unknown"


def _context_question_topic(value: Any) -> str:
    if isinstance(value, PracticeRecommendation):
        return value.knowledge_point.strip() or _clean_topic(value.question)
    if isinstance(value, dict):
        explicit_topic = _context_explicit_topic(value)
        if explicit_topic:
            return explicit_topic
        return _clean_topic(str(value.get("question") or value.get("content") or ""))
    if isinstance(value, list) and value:
        return _context_question_topic(value[0])
    text = str(value or "").strip()
    return _clean_topic(text) if text else ""


def _context_explicit_topic(value: Any) -> str:
    if isinstance(value, PracticeRecommendation):
        return value.knowledge_point.strip()[:60]
    if isinstance(value, dict):
        for key in ("knowledge_point", "topic", "active_topic", "current_question_topic", "concept", "concept_name", "title"):
            topic = str(value.get(key) or "").strip()
            if topic:
                return topic[:60]
    return ""


def _mentions_weak_points(message: str) -> bool:
    return any(term in message for term in WEAK_POINT_TERMS)


def _is_question_construction_explanation(message: str) -> bool:
    compact = _normalize_topic_for_compare(message)
    return any(
        marker in compact
        for marker in (
            "怎么出这道题",
            "如何出这道题",
            "为什么这么出题",
            "讲讲怎么出",
            "讲一下怎么出",
            "解释怎么出",
        )
    )


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
        r"(帮我|请|给我|来|出|生成|做|练习|刷题|题目|题|单选题|单选|选择题|多选题|多选|判断题|判断|简答题|简答|问答题|问答|难度|中等|简单|困难|基础|几道|一些|点)",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    topic = re.sub(r"\s+", " ", topic).strip(" ：:，,。.!！?？「」『』")
    return topic[:60]


def _clean_english_topic(value: str) -> str:
    topic = re.sub(
        r"\b(?:please|me|on|about|for|around|with|generate|create|make|write|build|give|"
        r"one|a|two|three|four|five|six|seven|eight|nine|ten|some|few|"
        r"easy|medium|hard|practice|questions?|quizzes|quiz|mcqs?|multiple|choice|single|test|drill)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    topic = re.sub(r"\s+", " ", topic).strip(" ：:，,。.!！?？\"'")
    return topic[:60]
