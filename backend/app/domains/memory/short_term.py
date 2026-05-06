"""
Short-term Memory
=================
负责最近消息抽取、短期上下文格式化，以及追问依赖判断。
"""

from __future__ import annotations

import re
from typing import Any

MAX_SHORT_TERM_MESSAGES = 6
MAX_MESSAGE_PREVIEW_CHARS = 180

CONTEXT_DEPENDENT_PATTERNS = [
    r"^(它|这个|这个概念|这个知识点|这个题|这一步|这道题|那这个|那这个呢)",
    r"(刚才|上一题|上一个|前面|前文|前一步|继续|接着|再讲|再说|再解释)",
    r"^(为什么|那为什么|怎么做|那怎么做|然后呢|接下来呢)$",
    r"^(能|可以)?(给我|帮我)?(讲|解释|展开|说)(一下|下)?.*(这个)?概念(不|吗|嘛)?[？?]?$",
]


def _truncate_text(text: str, max_length: int = MAX_MESSAGE_PREVIEW_CHARS) -> str:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1] + "…"


def extract_short_term_messages(
    session: dict[str, Any] | None,
    limit: int = MAX_SHORT_TERM_MESSAGES,
) -> list[dict[str, Any]]:
    if not session:
        return []

    messages = list(session.get("messages") or [])
    if limit <= 0:
        return []
    return messages[-limit:]


def build_short_term_context(messages: list[dict[str, Any]]) -> str:
    """把当前会话最近几轮消息格式化成短期记忆上下文。"""
    if not messages:
        return "（当前会话暂无历史上下文）"

    lines: list[str] = []
    for index, message in enumerate(messages, start=1):
        role = "学生" if message.get("role") == "user" else "助手"
        content = _truncate_text(str(message.get("content", "")))
        explanation = message.get("explanation") or {}
        topic = explanation.get("topic", "")

        if role == "助手" and topic:
            lines.append(f"{role}{index}（主题：{topic}）: {content}")
        else:
            lines.append(f"{role}{index}: {content}")

    return "\n".join(lines)


def is_context_dependent_question(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", (question or "")).strip().lower()
    if not normalized:
        return False

    if len(normalized) <= 10:
        return True

    for pattern in CONTEXT_DEPENDENT_PATTERNS:
        if re.search(pattern, normalized):
            return True

    return False
