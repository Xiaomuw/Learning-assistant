"""
路由 Agent — 完整实现
======================
职责：分析用户问题，判断 question_type。

使用 LangChain structured output + Pydantic BaseModel
让 LLM 输出固定分类枚举及置信度，低置信度时回退为 concept。

分类标签：
  - concept   : 概念理解类（"什么是xxx"、"解释xxx"、"怎么理解"）
  - problem   : 解题求助类（发来一道具体题目要求解答）
  - practice  : 练习出题类（"给我出几道题"、"我要练习"）
  - review    : 复习巩固类（"帮我复习"、"我哪里错了"、"薄弱点"）
  - meta      : 助手元问题（"你是什么模型"、"你是谁"、"你能做什么"）
  - smalltalk : 寒暄闲聊（"你好"、"在吗"、"hi"、"早上好"）
"""

from __future__ import annotations

import json
import re
from enum import Enum
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

class QuestionType(str, Enum):
    """问题类型枚举"""
    CONCEPT = "concept"
    PROBLEM = "problem"
    PRACTICE = "practice"
    REVIEW = "review"
    META = "meta"
    SMALLTALK = "smalltalk"


class RouterOutput(BaseModel):
    """路由 Agent 的结构化输出"""

    question_type: QuestionType = Field(
        description=(
            "用户问题的分类标签。"
            "concept: 概念理解类；"
            "problem: 解题求助类；"
            "practice: 练习出题类；"
            "review: 复习巩固类；"
            "meta: 询问助手/模型/能力/当前知识库等元问题；"
            "smalltalk: 寒暄、打招呼、确认是否在线等闲聊。"
        )
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="对该分类结果的置信度，范围 0.0 ~ 1.0",
    )

    reasoning: str = Field(
        description="简要说明判断理由（一两句话）",
    )


# ============================================================
# Prompt
# ============================================================

ROUTER_SYSTEM_PROMPT = """\
你是一个学习问题分类专家。请根据用户的问题，将其严格归入以下六种类型之一，\
并给出你的置信度（0.0~1.0）和简要理由。

## 分类标签及判断规则

### concept（概念理解类）
用户在询问定义、原理、概念解释。
典型特征：问"为什么""是什么""怎么理解""什么叫做""原理是什么""概念"

### problem（解题求助类）
用户发来一道具体题目，希望得到解答或解题过程。
典型特征：包含具体的数学公式、化学方程式、物理题目、编程题、\
阅读理解题等需要"解"的内容；出现"这道题""求解""计算""证明"

### practice（练习出题类）
用户请求系统生成练习题来做。
典型特征："出几道题""我要练习""来点题目""给我出题""再来一道""做题"

### review（复习巩固类）
用户想要复习已学内容、查看自己的薄弱点或错题。
典型特征："复习""总结一下""我哪里错了""薄弱点""回顾""帮我整理"

### meta（助手元问题）
用户在询问助手本身的信息，而不是某个学科知识点。
典型特征："你是什么模型""你是谁""你能做什么""当前用的什么模型""当前知识库是什么"

### smalltalk（寒暄闲聊）
用户只是打招呼、寒暄、确认助手是否在线，尚未进入具体学习问题。
典型特征："你好""hi""hello""在吗""早上好""晚上好""嗨"

## 注意事项
- 如果用户问的是助手身份、当前模型、当前能力、当前学科/知识库，必须优先归为 meta
- 如果用户只是打招呼或寒暄，优先归为 smalltalk，不要误判成 concept
- 如果问题模棱两可，优先判断最可能的类别并降低 confidence
- 如果完全无法判断，归为 concept 并将 confidence 设为 0.5 以下

## 输出格式
请严格以 JSON 格式输出，不包含任何其他内容：
{{"question_type": "concept或problem或practice或review或meta或smalltalk", "confidence": 0.9, "reasoning": "判断理由"}}
"""

ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ROUTER_SYSTEM_PROMPT),
    ("human", "{question}"),
])


# ============================================================
# LLM 实例
# ============================================================

def _get_llm() -> ChatOpenAI:
    """获取 gpt-4o-mini 实例"""
    return get_chat_llm(
        default_model="openai-gpt-4o-mini",
        temperature=0,
    )


# ============================================================
# 置信度回退
# ============================================================

CONFIDENCE_THRESHOLD = 0.7


META_PATTERNS = [
    r"^(你是谁|你是什么|你是干什么的|你是什么模型|你现在是什么模型|当前是什么模型)$",
    r"(你|当前|现在|这个助手|该助手).*(什么模型|哪个模型|用的什么模型|当前模型|模型是)",
    r"(你|这个助手|该助手).*(是谁|身份|角色|能做什么|会什么|可以做什么|有什么功能)",
    r"(当前|现在|这个|该).*(知识库|学科|助手|agent)",
]

SMALLTALK_PATTERNS = [
    r"^(你好|您好|嗨|hi|hello|hey)$",
    r"^(在吗|有人吗|还在吗)$",
    r"^(早上好|中午好|下午好|晚上好)$",
    r"^(哈喽|hello there|嗨嗨)$",
]

REVIEW_PATTERNS = [
    r"(复习|回顾|总结一下|总结下|梳理一下|薄弱点|错题|我哪里错了|帮我整理)",
]

PRACTICE_PATTERNS = [
    r"(给我出|帮我出|来[点些]|再来|出几道|出两道|出一道|练习题|题目|我要练习|我要刷题|给我几题)",
]

PROBLEM_PATTERNS = [
    r"(这道题|这题|求解|求证|证明|计算|怎么做|求.+值|解方程|编程题|算法题)",
]


def _classify_by_rules(question: str) -> RouterOutput | None:
    normalized = question.strip().lower()

    for pattern in META_PATTERNS:
        if re.search(pattern, normalized):
            return RouterOutput(
                question_type=QuestionType.META,
                confidence=0.98,
                reasoning="命中了助手身份/模型/能力/知识库相关关键词，属于元问题。",
            )

    for pattern in SMALLTALK_PATTERNS:
        if re.search(pattern, normalized):
            return RouterOutput(
                question_type=QuestionType.SMALLTALK,
                confidence=0.99,
                reasoning="命中了寒暄/打招呼表达，属于闲聊开场，不应进入知识检索。",
            )

    for pattern in REVIEW_PATTERNS:
        if re.search(pattern, normalized):
            return RouterOutput(
                question_type=QuestionType.REVIEW,
                confidence=0.93,
                reasoning="命中了复习、错题或薄弱点相关表达。",
            )

    for pattern in PRACTICE_PATTERNS:
        if re.search(pattern, normalized):
            return RouterOutput(
                question_type=QuestionType.PRACTICE,
                confidence=0.95,
                reasoning="命中了明确的出题/练习请求。",
            )

    for pattern in PROBLEM_PATTERNS:
        if re.search(pattern, normalized):
            return RouterOutput(
                question_type=QuestionType.PROBLEM,
                confidence=0.83,
                reasoning="命中了求解、证明、计算等解题信号。",
            )

    return None


def _apply_confidence_fallback(result: RouterOutput) -> str:
    """
    如果置信度低于阈值，回退为 concept。

    Args:
        result: LLM 返回的结构化分类结果

    Returns:
        最终的 question_type 字符串
    """
    if result.confidence < CONFIDENCE_THRESHOLD:
        logger.warning(
            f"⚠️ 置信度 {result.confidence:.2f} < {CONFIDENCE_THRESHOLD}，"
            f"原始分类 '{result.question_type.value}' 回退为 'concept'"
        )
        return "concept"
    return result.question_type.value


# ============================================================
# Agent 节点函数
# ============================================================

def router_agent(state: AgentState) -> dict[str, Any]:
    """
    LangGraph 节点：路由 Agent

    流程：
      1. 从 state 取出 question
      2. 使用 ChatOpenAI.with_structured_output(RouterOutput) 调用 LLM
      3. 获取 question_type + confidence
      4. confidence < 0.7 → 回退为 concept
      5. 返回 { "question_type": ... }
    """
    question = state["question"]
    logger.info(f"🔀 路由 Agent 收到问题: {question[:80]}...")

    rule_result = _classify_by_rules(question)
    if rule_result:
        logger.info(
            f"🔀 规则分类命中: type={rule_result.question_type.value}, "
            f"confidence={rule_result.confidence:.2f}, "
            f"reason={rule_result.reasoning}"
        )
        return {"question_type": rule_result.question_type.value}

    llm = _get_llm()
    chain = ROUTER_PROMPT | llm

    try:
        response = chain.invoke({"question": question})
        raw = response.content.strip()
        # 提取 JSON（兼容 markdown code block）
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        result = RouterOutput(
            question_type=data.get("question_type", "concept"),
            confidence=float(data.get("confidence", 0.8)),
            reasoning=data.get("reasoning", ""),
        )
        logger.info(
            f"🔀 LLM 分类结果: type={result.question_type.value}, "
            f"confidence={result.confidence:.2f}, "
            f"reason={result.reasoning}"
        )

        # 置信度检查 & 回退
        question_type = _apply_confidence_fallback(result)

    except Exception as e:
        logger.error(f"❌ 路由 Agent 调用失败: {e}")
        logger.info("🔀 兜底：默认分类为 concept")
        question_type = "concept"

    logger.info(f"🔀 最终路由结果: {question_type}")
    return {"question_type": question_type}
