from __future__ import annotations

import re
from dataclasses import dataclass


QUESTION_STABLE_KNOWLEDGE = "stable_knowledge"
QUESTION_REALTIME_OR_FRESH = "realtime_or_fresh"
QUESTION_META_TOOL_USAGE = "meta_tool_usage"
QUESTION_GENERAL = "general"


@dataclass(frozen=True)
class QuestionBoundary:
    category: str
    reason: str
    signals: tuple[str, ...] = ()
    contains_relative_year: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "reason": self.reason,
            "signals": list(self.signals),
            "contains_relative_year": self.contains_relative_year,
        }


def classify_question_boundary(question: str, *, current_date: str | None = None) -> QuestionBoundary:
    """Classify a QA question by fact freshness and trace-dependency.

    This intentionally stays rule-based: the boundary controls whether a model
    is allowed to make current-world claims, so it must be deterministic and
    testable instead of left to model phrasing.
    """

    text = _compact(question)
    lowered = text.lower()
    meta_signals = _matched_terms(text, lowered, _META_TOOL_USAGE_TERMS)
    if meta_signals:
        return QuestionBoundary(
            category=QUESTION_META_TOOL_USAGE,
            reason="tool_usage_trace_question",
            signals=tuple(meta_signals),
            contains_relative_year=_contains_relative_year(text),
        )

    realtime_signals = _matched_terms(text, lowered, _REALTIME_TERMS)
    if _is_openai_current_status_question(text, lowered):
        realtime_signals.append("openai_gpt_current_status")
    if realtime_signals:
        return QuestionBoundary(
            category=QUESTION_REALTIME_OR_FRESH,
            reason="realtime_or_fresh_signal",
            signals=tuple(dict.fromkeys(realtime_signals)),
            contains_relative_year=_contains_relative_year(text),
        )

    stable_signals = _matched_terms(text, lowered, _STABLE_KNOWLEDGE_TERMS)
    if stable_signals or _looks_like_stable_definition_question(text, lowered):
        return QuestionBoundary(
            category=QUESTION_STABLE_KNOWLEDGE,
            reason="stable_knowledge_signal",
            signals=tuple(stable_signals or ("definition_shape",)),
            contains_relative_year=False,
        )

    _ = current_date
    return QuestionBoundary(
        category=QUESTION_GENERAL,
        reason="no_specific_fact_boundary_signal",
        signals=(),
        contains_relative_year=False,
    )


def is_meta_tool_usage_question(question: str) -> bool:
    return classify_question_boundary(question).category == QUESTION_META_TOOL_USAGE


def is_realtime_or_fresh_question(question: str) -> bool:
    return classify_question_boundary(question).category == QUESTION_REALTIME_OR_FRESH


def is_stable_knowledge_question(question: str) -> bool:
    return classify_question_boundary(question).category == QUESTION_STABLE_KNOWLEDGE


def _compact(question: str) -> str:
    return " ".join(str(question or "").split()).strip()


def _matched_terms(text: str, lowered: str, terms: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    for term in terms:
        needle = term.lower()
        if term in text or needle in lowered:
            matches.append(term)
    return matches


def _contains_relative_year(text: str) -> bool:
    return "今年" in text or "this year" in text.lower()


def _looks_like_stable_definition_question(text: str, lowered: str) -> bool:
    if not text:
        return False
    if any(term in text for term in ("什么是", "什么叫", "解释一下", "解释")):
        return True
    if any(term in lowered for term in ("what is", "define ", "explain ")):
        return True
    return False


def _is_openai_current_status_question(text: str, lowered: str) -> bool:
    vendor_signal = any(term in lowered for term in ("openai", "gpt", "chatgpt", "api", "模型"))
    current_signal = any(
        term in text or term in lowered
        for term in (
            "今年",
            "现在",
            "最新",
            "目前",
            "当前",
            "发布到",
            "发布了",
            "版本",
            "current",
            "latest",
            "released",
            "version",
        )
    )
    return vendor_signal and current_signal


_META_TOOL_USAGE_TERMS = (
    "刚刚有联网",
    "刚才有联网",
    "有没有联网",
    "有联网搜索吗",
    "联网搜索了吗",
    "调用搜索了吗",
    "有没有调用搜索",
    "你查资料了吗",
    "你刚刚怎么查",
    "为什么是 0 次工具调用",
    "为什么是0次工具调用",
    "0 次工具调用",
    "用了什么工具",
    "你用了什么工具",
    "工具调用",
    "did you search",
    "did you use web",
    "tool call",
    "tools did you use",
)


_REALTIME_TERMS = (
    "今年",
    "现在",
    "最新",
    "目前",
    "当前",
    "今天",
    "刚刚",
    "最近",
    "发布到哪个版本",
    "发布到什么版本",
    "发布了哪个版本",
    "当前版本",
    "价格",
    "排名",
    "政策",
    "法律法规",
    "新闻",
    "赛事",
    "天气",
    "股票",
    "汇率",
    "官网最新",
    "浏览器支持",
    "this year",
    "now",
    "latest",
    "current",
    "today",
    "news",
    "weather",
    "price",
    "ranking",
    "version",
)


_STABLE_KNOWLEDGE_TERMS = (
    "什么是 http",
    "什么是HTTP",
    "http 是什么",
    "HTTP 是什么",
    "tcp 和 udp 的区别",
    "TCP 和 UDP 的区别",
    "二叉树是什么",
    "什么是二叉树",
    "javascript promise",
    "JavaScript Promise",
    "什么是 promise",
    "什么是 Promise",
)
