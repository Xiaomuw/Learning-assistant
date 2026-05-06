"""
Long-term Memory
================
负责用户画像 / 学习画像的长期上下文格式化。
"""

from __future__ import annotations

from typing import Any


def build_long_term_context(
    user_profile: dict[str, Any],
    memory: dict[str, Any],
) -> str:
    """把用户长期学习画像整理成可直接注入 prompt 的摘要。"""
    lines: list[str] = []

    display_name = str(user_profile.get("display_name", "") or "").strip()
    if display_name:
        lines.append(f"用户昵称：{display_name}")

    weak_points = list(memory.get("weak_points", []) or [])
    if weak_points:
        lines.append(f"长期薄弱点：{', '.join(weak_points[:5])}")

    recent_topics = list(memory.get("recent_topics", []) or [])
    if recent_topics:
        lines.append(f"最近学习主题：{', '.join(recent_topics[:5])}")

    error_count = dict(memory.get("error_count", {}) or {})
    if error_count:
        top_errors = sorted(error_count.items(), key=lambda item: item[1], reverse=True)[:5]
        lines.append(
            "高频错误统计："
            + ", ".join(f"{topic}(错{count}次)" for topic, count in top_errors)
        )

    last_session = str(memory.get("last_session", "") or "").strip()
    if last_session:
        lines.append(f"最近一次学习记录：{last_session}")

    if not lines:
        return "（暂无长期学习记忆，这可能是新用户）"
    return "\n".join(lines)
