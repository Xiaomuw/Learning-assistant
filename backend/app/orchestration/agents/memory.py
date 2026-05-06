"""
记忆 Agent — 完整实现
======================
职责：
  在每轮对话结束后更新用户学习记忆，供下次对话使用。
  纯逻辑处理，不调用 LLM。

  当前实现以数据库作为唯一长期事实来源，
  不再依赖 JSON 文件或 LangGraph 的进程内 checkpointer。

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

from app.domains.mastery.service import record_exposure
from app.domains.memory.gateway import load_user_memory, save_user_memory_state
from app.shared.schemas.state import AgentState, Memory


# ============================================================
# 常量
# ============================================================

MAX_RECENT_TOPICS = 10
MAX_WEAK_POINTS = 15  # 薄弱点上限，防止无限膨耀0


def _update_weak_points(
    weak_points: list[str],
    mistakes: str,
    topic: str,
    max_len: int = MAX_WEAK_POINTS,
) -> list[str]:
    """
    如果 explanation.mistakes 中提到的知识点不在 weak_points 里，追加进去。
    超过 max_len 后自动移除最早的条目（先进先出）。

    mistakes 统一为 str，表示当前最值得提醒的一个易错点。
    """
    updated = list(weak_points)  # 浅拷贝

    mistake_items = [mistakes] if mistakes else []

    # 只有真实出现卡点/错因时才写入薄弱点；普通曝光只进入 mastery exposure。
    items_to_check = mistake_items

    for item in items_to_check:
        item_stripped = item.strip()
        if item_stripped and item_stripped not in updated:
            updated.append(item_stripped)
            logger.debug(f"  + weak_point: '{item_stripped}'")

    # 超限时移除最早的条目
    if len(updated) > max_len:
        removed = updated[:len(updated) - max_len]
        updated = updated[-max_len:]
        logger.debug(f"  ✂ weak_points 超限，移除最早: {removed}")

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
      1. 从 state 读取 user_id, session_id, question_type, explanation
      2. 从数据库加载该用户已有记忆
      3. 合并更新：
         - weak_points  ← explanation.mistakes（带上限保护）
         - error_count  ← explanation.topic +1
         - recent_topics ← topic 插入头部，保留最近 10 个
         - last_session ← session_id@timestamp
         - last_question_type ← 当前 question_type，供下轮路由追问继承
      4. 写回数据库
      5. 将 similar 中的前 2 条写入 session_memory.open_loops
      6. 返回 { "memory": updated_memory }
    """
    user_id = state.get("user_id", "anonymous")
    session_id = state.get("session_id", "unknown")
    subject_id = state.get("subject_id", "general")
    question_type = str(state.get("question_type", "") or "")
    explanation = state.get("explanation", {})

    topic = explanation.get("topic", "")
    mistakes = str(explanation.get("mistakes", "") or "")
    similar = list(explanation.get("similar", []) or [])

    logger.info(
        f"🧠 记忆 Agent 开始 | user={user_id} | "
        f"session={session_id[:16]}… | topic='{topic}' | type={question_type}"
    )

    # ---- 1. 加载已有记忆 ----
    existing = load_user_memory(user_id)

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
        "last_question_type": question_type,  # 供下轮路由追问继承
    }

    # ---- 4. 持久化写回 ----
    save_user_memory_state(user_id, updated_memory)
    try:
        record_exposure(
            user_id=user_id,
            subject_id=str(subject_id or "general"),
            knowledge_point=topic,
        )
    except Exception as exc:
        logger.warning(f"⚠️ 知识点 exposure 统计失败: {exc}")

    # ---- 5. 将 similar 写入 session open_loops （形成追问线索）----
    open_loops_update: dict[str, Any] = {}
    if similar:
        open_loop_items = [s for s in similar if isinstance(s, str) and s.strip()][:2]
        if open_loop_items:
            existing_session = state.get("session_memory") or {}
            open_loops_update = {
                "session_memory": {
                    **existing_session,
                    "open_loops": open_loop_items,
                    "last_question_type": question_type,
                }
            }
            logger.debug(f"  🔗 open_loops 写入: {open_loop_items}")

    logger.info(
        f"🧠 记忆更新完成 | "
        f"weak_points={len(new_weak_points)} | "
        f"error_count['{topic}']={new_error_count.get(topic, 0)} | "
        f"recent={len(new_recent_topics)} | "
        f"last_question_type={question_type}"
    )

    return {"memory": updated_memory, **open_loops_update}
