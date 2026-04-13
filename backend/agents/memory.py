"""
记忆 Agent — 完整实现
======================
职责：
  在每轮对话结束后更新用户学习记忆，供下次对话使用。
  纯逻辑处理，不调用 LLM。

  使用 JSON 文件持久化（路径: data/memory/{user_id}.json），
  后续可替换为数据库。

更新规则：
  - weak_points:  explanation.mistakes 中提到的知识点若不在列表中则追加
  - error_count:  explanation.topic 每次出现 +1
  - recent_topics: 保留最近 10 个知识点，先进先出
  - last_session: 记录本次 session_id + 时间戳
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from db.repositories import get_user_memory, save_user_memory
from schemas.state import AgentState, Memory


# ============================================================
# 常量
# ============================================================

MAX_RECENT_TOPICS = 10


def _load_memory(user_id: str) -> Memory:
    """
    从数据库加载用户记忆。
    """
    try:
        memory = get_user_memory(user_id)

        logger.info(
            f"📂 加载用户 {user_id} 记忆成功 | "
            f"weak={len(memory['weak_points'])} | "
            f"topics={len(memory['recent_topics'])}"
        )
        return memory

    except Exception as e:
        logger.warning(f"⚠️ 读取用户 {user_id} 记忆失败: {e}")
        return {
            "weak_points": [],
            "error_count": {},
            "recent_topics": [],
            "last_session": "",
        }


# ============================================================
# 持久化：写入
# ============================================================

def _save_memory(user_id: str, memory: Memory) -> None:
    """
    将用户记忆写入数据库。
    """
    try:
        save_user_memory(user_id, dict(memory))
        logger.info(f"💾 用户 {user_id} 记忆已保存到数据库")
    except Exception as e:
        logger.warning(f"⚠️ 保存用户 {user_id} 记忆失败: {e}")


# ============================================================
# 记忆更新逻辑
# ============================================================

def _update_weak_points(
    weak_points: list[str],
    mistakes: str | list[str],
    topic: str,
) -> list[str]:
    """
    如果 explanation.mistakes 中提到的知识点不在 weak_points 里，追加进去。

    mistakes 可能是 str（explainer 输出）或 list[str]，统一处理。
    """
    updated = list(weak_points)  # 浅拷贝

    # 统一转为列表
    if isinstance(mistakes, str):
        mistake_items = [mistakes] if mistakes else []
    else:
        mistake_items = list(mistakes)

    # 将 topic 本身也视为潜在的薄弱点
    items_to_check = mistake_items + ([topic] if topic else [])

    for item in items_to_check:
        item_stripped = item.strip()
        if item_stripped and item_stripped not in updated:
            updated.append(item_stripped)
            logger.debug(f"  + weak_point: '{item_stripped}'")

    return updated


def _update_error_count(
    error_count: dict[str, int],
    topic: str,
) -> dict[str, int]:
    """
    error_count[topic] += 1，每次对话该知识点出现就计数。
    """
    updated = dict(error_count)  # 浅拷贝

    if topic:
        prev = updated.get(topic, 0)
        updated[topic] = prev + 1
        logger.debug(f"  ✚ error_count['{topic}']: {prev} → {prev + 1}")

    return updated


def _update_recent_topics(
    recent_topics: list[str],
    topic: str,
    max_len: int = MAX_RECENT_TOPICS,
) -> list[str]:
    """
    将新知识点加入列表头部，去重，保留最近 max_len 个（先进先出）。
    """
    updated = list(recent_topics)  # 浅拷贝

    if not topic:
        return updated

    # 如果已存在，先移除旧位置
    if topic in updated:
        updated.remove(topic)

    # 插入头部（最近学的在最前）
    updated.insert(0, topic)

    # 截断到 max_len
    if len(updated) > max_len:
        removed = updated[max_len:]
        updated = updated[:max_len]
        logger.debug(f"  ✂ recent_topics 截断，移除: {removed}")

    return updated


def _make_session_stamp(session_id: str) -> str:
    """生成 session_id + 时间戳 的标识字符串"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{session_id}@{now}"


# ============================================================
# Agent 节点函数
# ============================================================

def memory_agent(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点：记忆 Agent

    流程：
      1. 从 state 读取 user_id, session_id, explanation
      2. 从 JSON 文件加载该用户已有记忆
      3. 合并更新：
         - weak_points  ← explanation.mistakes
         - error_count  ← explanation.topic +1
         - recent_topics ← topic 插入头部，保留最近 10 个
         - last_session ← session_id@timestamp
      4. 写回 JSON 文件
      5. 返回 { "memory": updated_memory }
    """
    user_id = state.get("user_id", "anonymous")
    session_id = state.get("session_id", "unknown")
    explanation = state.get("explanation", {})

    topic = explanation.get("topic", "")
    mistakes = explanation.get("mistakes", "")

    logger.info(
        f"🧠 记忆 Agent 开始 | user={user_id} | "
        f"session={session_id[:16]}… | topic='{topic}'"
    )

    # ---- 1. 加载已有记忆 ----
    existing = _load_memory(user_id)

    # ---- 2. 更新各字段 ----
    new_weak_points = _update_weak_points(
        existing.get("weak_points", []),
        mistakes,
        topic,
    )

    new_error_count = _update_error_count(
        existing.get("error_count", {}),
        topic,
    )

    new_recent_topics = _update_recent_topics(
        existing.get("recent_topics", []),
        topic,
    )

    new_last_session = _make_session_stamp(session_id)

    # ---- 3. 组装更新后的记忆 ----
    updated_memory: Memory = {
        "weak_points": new_weak_points,
        "error_count": new_error_count,
        "recent_topics": new_recent_topics,
        "last_session": new_last_session,
    }

    # ---- 4. 持久化写回 ----
    _save_memory(user_id, updated_memory)

    logger.info(
        f"🧠 记忆更新完成 | "
        f"weak_points={len(new_weak_points)} | "
        f"error_count['{topic}']={new_error_count.get(topic, 0)} | "
        f"recent={len(new_recent_topics)} | "
        f"session={new_last_session}"
    )

    return {"memory": updated_memory}
