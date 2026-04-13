"""
LangGraph TypedDict State 定义
==============================
所有 Agent 共享的全局状态对象。
LangGraph 会在节点之间自动传递和合并 State。
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


# ---------- 子结构：结构化讲解 ----------
class Explanation(TypedDict, total=False):
    """讲解 Agent 输出的结构化解释"""
    topic: str                  # 所属知识点/主题
    thinking: str               # 解题思路 / 概念推导过程
    steps: list[str]            # 分步讲解
    mistakes: list[str]         # 常见错误 / 易错点
    similar: list[str]          # 相似题目 / 延伸知识点


# ---------- 子结构：学习记忆 ----------
class Memory(TypedDict, total=False):
    """记忆 Agent 维护的用户学习画像"""
    weak_points: list[str]      # 薄弱知识点列表
    error_count: dict[str, int] # 各知识点错误计数  { "二次函数": 3, ... }
    recent_topics: list[str]    # 最近学习的知识点（按时间倒序）
    last_session: str           # 上次会话标识（session_id + 时间戳）


# ---------- 子结构：练习题 ----------
class QuizItem(TypedDict, total=False):
    """出题 Agent 生成的单道练习题"""
    difficulty: Literal["基础", "变式", "易错"]  # 出题难度
    question: str               # 题目正文
    hint: str                   # 提示（不透露答案，只给方向）
    answer: str                 # 完整答案
    knowledge_point: str        # 对应知识点


# ---------- 主 State ----------
class AgentState(TypedDict, total=False):
    """
    LangGraph 全局 State
    ---------------------
    每个 Agent 节点从 state 中读取所需字段，处理后将结果写回 state。
    使用 `total=False` 使所有字段可选，方便各节点按需填充。
    """

    # ---- 会话标识 ----
    user_id: str                # 用户唯一标识
    session_id: str             # 当前会话 ID

    # ---- 学科 ----
    subject_id: str             # 当前选中的学科 ID（如 "computer-network"）
    subject_name: str           # 学科显示名（如 "计算机网络"，供 prompt 使用）
    subject_description: str    # 当前学科的环境提示词 / 人设描述

    # ---- 输入 ----
    question: str               # 用户提出的原始问题
    user_style_name: str        # 用户自定义的助手风格名称
    user_style_prompt: str      # 用户自定义的助手说话风格 / 角色提示词

    # ---- 路由结果 ----
    question_type: Literal[
        "concept",   # 概念理解类
        "problem",   # 解题求助类
        "practice",  # 练习出题类
        "review",    # 复习巩固类
        "meta",      # 助手/模型/能力等元问题
        "smalltalk", # 寒暄 / 闲聊 / 开场白
    ]

    # ---- 检索结果 ----
    retrieved_docs: list[dict[str, Any]]
    # 每个 doc: { "content": str, "metadata": dict, "score": float }
    is_rewritten: bool              # 检索 Agent 是否重写了原始问题

    # ---- 讲解结果 ----
    explanation: Explanation

    # ---- 练习题 ----
    quiz_items: list[QuizItem]      # 出题 Agent 生成的练习题列表

    # ---- 记忆 ----
    memory: Memory

    # ---- 最终回复（聚合后返回给前端） ----
    final_answer: str
