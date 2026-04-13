"""
出题 Agent — 完整实现
======================
职责：
  根据当前知识点和用户掌握情况，生成 2 道个性化练习题。

  难度判定（基于 error_count）：
    - error_count <= 1 → 基础题（直接套公式）
    - error_count 2~3  → 变式题（改变已知条件）
    - error_count >= 4  → 易错题（专门针对常见误区）

  输出 schema（每道题）：
    difficulty, question, hint, answer, knowledge_point
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from pydantic import BaseModel, Field

from schemas.state import AgentState
from tools.model_provider import get_chat_llm


# ============================================================
# Structured Output Schema
# ============================================================

class QuizItemOutput(BaseModel):
    """单道练习题的结构化输出"""

    difficulty: Literal["基础", "变式", "易错"] = Field(
        description="题目难度等级：基础（套公式）、变式（改条件）、易错（针对误区）",
    )
    question: str = Field(
        description="题目正文，包含完整的题干和所有已知条件",
    )
    hint: str = Field(
        description="解题提示，给出思考方向但不透露答案",
    )
    answer: str = Field(
        description="完整答案，包含关键步骤和最终结果",
    )
    knowledge_point: str = Field(
        description="本题考查的具体知识点名称",
    )


class QuizListOutput(BaseModel):
    """出题 Agent 的完整输出：2 道练习题"""

    items: list[QuizItemOutput] = Field(
        min_length=2,
        max_length=2,
        description="恰好 2 道练习题",
    )


# ============================================================
# 难度判定
# ============================================================

def _determine_difficulty(
    topic: str,
    error_count: dict[str, int],
) -> Literal["基础", "变式", "易错"]:
    """
    根据该知识点的历史错误次数决定出题难度。

    规则：
      error_count <= 1 → 基础（直接套公式）
      error_count 2~3  → 变式（改变已知条件）
      error_count >= 4  → 易错（针对常见误区）
    """
    errors = error_count.get(topic, 0)

    if errors <= 1:
        difficulty = "基础"
    elif errors <= 3:
        difficulty = "变式"
    else:
        difficulty = "易错"

    logger.info(
        f"📊 难度判定: topic='{topic}', "
        f"error_count={errors} → difficulty='{difficulty}'"
    )
    return difficulty


# ============================================================
# Prompt 模板
# ============================================================

QUIZ_SYSTEM_PROMPT = """\
你是一位经验丰富的出题老师。请根据以下信息为学生生成恰好 2 道练习题。

## 出题知识点
{topic}

## 要求的难度级别：{difficulty}

### 难度说明
- 基础：直接运用公式或定义即可解答，不设陷阱
- 变式：在基本题型基础上改变已知条件或问法，需要灵活运用知识
- 易错：专门针对该知识点最常见的误区设计，容易做错的题目

## 学生的薄弱点
{weak_points_info}

## 用户期望的表达风格
{user_style_instruction}

## 重要约束
1. 两道题必须属于同一知识点「{topic}」，但题目内容和数据不能相同
2. 题目不能与学生的原始问题完全相同（原始问题见下方）
3. hint 只给方向性提示，绝对不能透露答案
4. answer 要有关键计算步骤和最终结果
5. 两道题之间要有一定区分度，不能仅仅换个数字

## 学生当前在学的问题（避免重复）
{original_question}
"""

QUIZ_PROMPT = ChatPromptTemplate.from_messages([
    ("system", QUIZ_SYSTEM_PROMPT),
    ("human", '请根据以上要求生成 2 道练习题。严格以 JSON 格式输出，不包含任何其他文字，格式如下：\n{{"items": [{{"difficulty": "基础/变式/易错", "question": "题目", "hint": "提示", "answer": "答案", "knowledge_point": "知识点"}}, ...]}}'),
])


# ============================================================
# 辅助函数
# ============================================================

def _get_llm() -> ChatOpenAI:
    """获取 gpt-4o-mini 实例"""
    return get_chat_llm(
        default_model="openai-gpt-4o-mini",
        temperature=0.8,  # 出题需要多样性
    )


def _format_weak_points(
    weak_points: list[str],
    error_count: dict[str, int],
    topic: str,
) -> str:
    """格式化薄弱点信息供 prompt 使用"""
    lines: list[str] = []

    # 当前知识点的错误情况
    topic_errors = error_count.get(topic, 0)
    if topic_errors > 0:
        lines.append(f"当前知识点「{topic}」历史错误 {topic_errors} 次")

    # 相关的薄弱点
    related = [wp for wp in weak_points if wp != topic]
    if related:
        lines.append(f"其他薄弱知识点：{', '.join(related[:5])}")

    if not lines:
        lines.append("暂无历史错误记录，这可能是新知识点。")

    return "\n".join(lines)


def _format_user_style_instruction(style_name: str, style_prompt: str) -> str:
    if not style_prompt.strip():
        return "未设置额外口吻要求，保持自然、专业、清晰。"

    if style_name.strip():
        return f"{style_name.strip()}：{style_prompt.strip()}"

    return style_prompt.strip()


def _infer_topic_from_question(question: str, subject_name: str) -> str:
    """在 practice 路径没有 explanation.topic 时，从原问题里提取主题。"""
    english_terms = re.findall(r"[A-Za-z][A-Za-z0-9+/#._-]*", question)
    if english_terms:
        return english_terms[0]

    patterns = [
        r"关于(.+?)(?:的)?(?:练习题|题目|题|知识点)",
        r"(.+?)(?:的)?(?:练习题|题目|题)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            candidate = match.group(1).strip(" ，。！？、")
            if candidate:
                return candidate[:30]

    cleaned = re.sub(
        r"(给我|请|帮我|来|出|几道|两道|一道|一些|再来|练习题|题目|做题|我要|关于|帮忙|生成)",
        " ",
        question,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，。！？、")
    if cleaned:
        return cleaned[:30]

    return subject_name or "综合"


# ============================================================
# Agent 节点函数
# ============================================================

def quiz_agent(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点：出题 Agent

    流程：
      1. 从 state 读取 explanation.topic、memory.weak_points、memory.error_count
      2. 根据 error_count 判定出题难度
      3. 使用 ChatOpenAI.with_structured_output(QuizListOutput) 生成 2 道题
      4. 确保题目与原始问题不重复
      5. 返回 { "quiz_items": [...] }
    """
    explanation = state.get("explanation", {})
    memory = state.get("memory", {})
    question = state.get("question", "")

    subject_name = state.get("subject_name", "综合")
    topic = explanation.get("topic") or _infer_topic_from_question(question, subject_name)
    weak_points = memory.get("weak_points", [])
    error_count = memory.get("error_count", {})
    user_style_instruction = _format_user_style_instruction(
        state.get("user_style_name", ""),
        state.get("user_style_prompt", ""),
    )

    logger.info(f"✏️ 出题 Agent 开始 | topic='{topic}' | question='{question[:50]}…'")

    # ---- 判定难度 ----
    difficulty = _determine_difficulty(topic, error_count)

    # ---- 组装 prompt 参数 ----
    weak_points_info = _format_weak_points(weak_points, error_count, topic)

    # ---- 调用 LLM ----
    llm = _get_llm()
    chain = QUIZ_PROMPT | llm

    try:
        response = chain.invoke({
            "topic": topic,
            "difficulty": difficulty,
            "weak_points_info": weak_points_info,
            "original_question": question or "（无原始问题）",
            "user_style_instruction": user_style_instruction,
        })
        raw = response.content.strip()
        # 提取 JSON（兼容 markdown code block）
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)

        items_data = data.get("items", data) if isinstance(data, dict) else data
        if isinstance(items_data, dict):
            items_data = [items_data]

        quiz_items = [
            {
                "difficulty": item.get("difficulty", difficulty),
                "question": item.get("question", ""),
                "hint": item.get("hint", ""),
                "answer": item.get("answer", ""),
                "knowledge_point": item.get("knowledge_point", topic),
            }
            for item in items_data
        ]

        logger.info(
            f"✏️ 出题完成 | 共 {len(quiz_items)} 道 | "
            f"难度=[{', '.join(q['difficulty'] for q in quiz_items)}]"
        )

        # 验证题目不与原始问题完全相同
        for i, qi in enumerate(quiz_items):
            if qi["question"].strip() == question.strip():
                logger.warning(
                    f"⚠️ 第 {i+1} 题与原始问题完全相同，追加变化标记"
                )
                qi["question"] += "（请用不同方法解答）"

        final_answer = (
            f"我已经围绕「{topic}」准备了 {len(quiz_items)} 道{difficulty}练习题，"
            "你可以直接去刷题页继续做。"
        )

    except Exception as e:
        logger.error(f"❌ 出题 Agent 调用失败: {e}")
        quiz_items = []
        final_answer = (
            f"关于「{topic}」的练习题生成超时或失败了。"
            "这次我没有保存残缺题目，你可以直接重试。"
        )

    return {
        "quiz_items": quiz_items,
        "final_answer": final_answer,
    }
