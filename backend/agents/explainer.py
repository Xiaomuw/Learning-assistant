"""
讲解 Agent — 完整实现
======================
职责：
  根据检索文档、用户问题、问题类型和学习记忆，
  以"苏格拉底式助教"角色生成结构化分层讲解。

  不同 question_type 采用不同讲解风格：
    - concept  → 侧重直觉理解，多用类比
    - problem  → 侧重解题思路，不直接给答案，前两步只给方向
    - practice → 更简洁，直接给步骤
    - review   → 结合 memory.weak_points 重点强调易错点
"""

from __future__ import annotations

import json
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, Field

from schemas.state import AgentState
from tools.model_provider import get_chat_llm


# ============================================================
# Structured Output Schema
# ============================================================

class ExplanationOutput(BaseModel):
    """讲解 Agent 的结构化输出"""

    topic: str = Field(
        description="本题/本问题考查的核心知识点名称",
    )
    thinking: str = Field(
        description="解题思路或概念理解的切入点，1-2 句话概述",
    )
    steps: list[str] = Field(
        description="分步骤讲解过程，每步一句话。problem 类型时前两步只给方向提示不给具体计算",
    )
    mistakes: str = Field(
        description="针对该知识点最常见的一个易错点，用一句话描述",
    )
    similar: list[str] = Field(
        min_length=2,
        max_length=3,
        description="2-3 个相关的知识点或题型名称，帮助学生建立知识网络",
    )


# ============================================================
# 风格指令（按 question_type 切换）
# ============================================================

STYLE_INSTRUCTIONS: dict[str, str] = {
    "concept": (
        "【讲解风格：概念理解】\n"
        "- 用直觉化、生活化的语言解释概念\n"
        "- 多使用类比和比喻帮助学生建立直观理解\n"
        "- steps 从「为什么需要这个概念」出发，逐步深入到定义和性质\n"
        "- 避免上来就列公式，先让学生'感受'到概念的意义"
    ),
    "problem": (
        "【讲解风格：解题辅导 — 苏格拉底式引导】\n"
        "- 绝对不要直接给出最终答案或完整计算过程\n"
        "- thinking 只描述「从哪个角度切入」，不透露具体方法\n"
        "- steps 的前两步只给方向性提示（如「想想这道题的已知条件暗示了什么」），\n"
        "  不写出具体计算；从第三步开始可以逐步给出更具体的指引\n"
        "- 在最后一步用反问句引导学生自己完成最后一步\n"
        "- 目标是让学生「差一步就能自己做出来」"
    ),
    "practice": (
        "【讲解风格：练习简讲】\n"
        "- 保持简洁高效，不拖泥带水\n"
        "- steps 直接给出解题步骤，每步清晰明确\n"
        "- 适合学生快速参考，不需要过多引导"
    ),
    "review": (
        "【讲解风格：复习巩固】\n"
        "- 重点关注学生的薄弱环节（下方提供了薄弱知识点列表）\n"
        "- mistakes 要特别详细，结合学生历史易错点展开\n"
        "- steps 按「回忆要点 → 澄清易混淆点 → 强化记忆」的结构组织\n"
        "- similar 优先列出与薄弱点相关的知识"
    ),
}


# ============================================================
# Prompt 模板
# ============================================================

SYSTEM_PROMPT = """\
你是一位"苏格拉底式助教"——你的核心教学理念是：
不直接灌输知识，而是通过提问和引导帮助学生自己发现答案。
你耐心、鼓励、善于用简单的语言解释复杂的概念。

## 当前笔记本 / 知识库上下文
{notebook_context}

## 用户期望的回答风格
{user_style_instruction}

{style_instruction}

## 参考资料
以下是从知识库中检索到的相关文档，请基于这些内容进行讲解：
{context}

## 学生画像
{student_profile}

## 输出要求
请严格以 JSON 格式输出讲解内容，不包含任何其他文字，格式如下：
{{"topic": "知识点名称", "thinking": "解题思路", "steps": ["步骤1", "步骤2"], "mistakes": "易错点", "similar": ["相关知识1", "相关知识2"]}}
"""

HUMAN_PROMPT = "学生的问题：{question}"

EXPLAINER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
])


# ============================================================
# 辅助函数
# ============================================================

def _get_llm() -> ChatOpenAI:
    """获取 gpt-4o 实例（讲解 Agent 使用更强模型）"""
    return get_chat_llm(
        default_model="openai-gpt-4o-mini",
        temperature=0.3,       # 略带创造性，但保持准确
    )


def _format_context(docs: list[dict[str, Any]]) -> str:
    """将检索文档列表拼接为上下文字符串"""
    if not docs:
        return "（暂无参考资料，请根据你的知识进行讲解）"

    parts: list[str] = []
    for i, doc in enumerate(docs, 1):
        content = doc.get("content", "")
        score = doc.get("score", 0)
        parts.append(f"[文档{i}｜相关度 {score:.2f}]\n{content}")
    return "\n\n---\n\n".join(parts)


def _format_student_profile(
    question_type: str,
    memory: dict[str, Any],
) -> str:
    """格式化学生画像信息"""
    weak_points = memory.get("weak_points", [])
    error_count = memory.get("error_count", {})
    recent_topics = memory.get("recent_topics", [])

    lines: list[str] = []

    if weak_points:
        lines.append(f"薄弱知识点：{', '.join(weak_points)}")
    if error_count:
        top_errors = sorted(error_count.items(), key=lambda x: x[1], reverse=True)[:5]
        errors_str = ", ".join(f"{k}(错{v}次)" for k, v in top_errors)
        lines.append(f"高频错误：{errors_str}")
    if recent_topics:
        lines.append(f"最近学习：{', '.join(recent_topics[:5])}")

    if not lines:
        lines.append("暂无历史学习数据，这可能是新学生。")

    return "\n".join(lines)


def _get_style_instruction(question_type: str) -> str:
    """根据问题类型获取对应的讲解风格指令"""
    return STYLE_INSTRUCTIONS.get(question_type, STYLE_INSTRUCTIONS["concept"])


def _format_user_style_instruction(style_name: str, style_prompt: str) -> str:
    if not style_prompt.strip():
        return (
            "未设置额外角色扮演要求。请保持专业、自然、友好、易懂，"
            "但不要把自己说成某个虚构人物。"
        )

    if style_name.strip():
        return (
            f"用户选择的回答风格名称：{style_name.strip()}。\n"
            f"请严格按以下风格组织表达，但不要改变事实准确性和教学结构：\n"
            f"{style_prompt.strip()}"
        )

    return (
        "请严格按以下风格组织表达，但不要改变事实准确性和教学结构：\n"
        f"{style_prompt.strip()}"
    )


# ============================================================
# Agent 节点函数
# ============================================================

def explainer_agent(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点：讲解 Agent

    流程：
      1. 从 state 读取 question, retrieved_docs, question_type, memory
      2. 根据 question_type 选择讲解风格指令
      3. 格式化参考文档和学生画像
      4. 使用 ChatOpenAI(gpt-4o).with_structured_output(ExplanationOutput) 生成讲解
      5. 将结构化结果写入 state["explanation"]
    """
    question = state["question"]
    question_type = state.get("question_type", "concept")
    docs = state.get("retrieved_docs", [])
    memory = state.get("memory", {})
    subject_name = state.get("subject_name", "通用知识")

    logger.info(
        f"📖 讲解 Agent 开始 | [{subject_name}] type={question_type} | "
        f"文档数={len(docs)} | question={question[:60]}…"
    )

    # ---- 组装 prompt 参数 ----
    style_instruction = _get_style_instruction(question_type)
    context = _format_context(docs)
    student_profile = _format_student_profile(question_type, memory)
    subject_description = state.get("subject_description", "")
    user_style_name = state.get("user_style_name", "")
    user_style_prompt = state.get("user_style_prompt", "")

    if subject_name != "通用知识":
        notebook_context = f"当前知识库名称：{subject_name}。\n"
        if subject_description:
            notebook_context += f"【知识库简介】：{subject_description}\n"
        notebook_context += "请确保讲解尽量围绕该知识库覆盖的知识体系。"
    else:
        notebook_context = "当前为通用问答模式，不限定某个专用知识库。"

    user_style_instruction = _format_user_style_instruction(
        user_style_name,
        user_style_prompt,
    )

    # ---- 调用 LLM ----
    llm = _get_llm()
    chain = EXPLAINER_PROMPT | llm

    try:
        response = chain.invoke({
            "style_instruction": style_instruction,
            "context": context,
            "student_profile": student_profile,
            "notebook_context": notebook_context,
            "user_style_instruction": user_style_instruction,
            "question": question,
        })
        raw = response.content.strip()
        # 提取 JSON（兼容 markdown code block）
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)

        explanation = {
            "topic": data.get("topic", "未知"),
            "thinking": data.get("thinking", ""),
            "steps": data.get("steps", []),
            "mistakes": data.get("mistakes", "无"),
            "similar": data.get("similar", []),
        }

        logger.info(
            f"📖 讲解完成 | 知识点={explanation['topic']} | "
            f"步骤数={len(explanation['steps'])} | "
            f"易错点={explanation['mistakes'][:40]}…"
        )

    except Exception as e:
        logger.error(f"❌ 讲解 Agent 调用失败: {e}")
        explanation = {
            "topic": "未知",
            "thinking": "抱歉，讲解生成失败，请重新提问。",
            "steps": ["系统暂时无法生成讲解，请稍后重试。"],
            "mistakes": "无",
            "similar": ["请重新提问"],
        }

    return {"explanation": explanation}
