"""
元问题 Agent
============
职责：
  处理关于“当前助手是谁、正在使用什么模型、能做什么、当前学科是什么”
  这类不应进入知识检索或学习记忆链路的问题。
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from schemas.state import AgentState
from tools.model_provider import (
    DEFAULT_CHAT_MODEL,
    get_active_chat_model,
    list_selectable_chat_models,
)


def _resolve_model_snapshot() -> tuple[str, str, str]:
    model_id = get_active_chat_model(DEFAULT_CHAT_MODEL)
    label = model_id
    provider = "未知提供方"

    try:
        for option in list_selectable_chat_models():
            if option["id"] == model_id:
                label = option.get("label", model_id)
                provider = option.get("provider", provider)
                break
    except Exception as exc:
        logger.warning(f"⚠️ 获取模型元信息失败，回退为基础信息: {exc}")

    return model_id, label, provider


def _detect_meta_intent(question: str) -> str:
    normalized = question.strip().lower()

    model_patterns = (
        r"你.*(什么模型|哪个模型|用的什么模型|当前模型|现在模型)",
        r"(当前|现在|这个助手|该助手).*(什么模型|哪个模型|模型是|用的模型)",
        r"^(你是什么模型|你现在是什么模型|当前是什么模型|现在是什么模型)$",
    )
    identity_patterns = (
        r"^(你是谁|你是什么|你是干什么的)$",
        r"(你|这个助手|该助手).*(是谁|身份|角色)",
    )
    capability_patterns = (
        r"(你|这个助手|该助手).*(能做什么|会什么|可以做什么|有什么功能)",
        r"^(功能介绍|你能帮我什么)$",
    )
    subject_patterns = (
        r"(当前|现在|这个|该).*(学科|知识库|助手|agent)",
        r"^(当前助手是谁|当前知识库是什么|我现在在和谁对话)$",
    )
    greeting_patterns = (
        r"^(你好|您好|嗨|hi|hello|hey)$",
        r"^(在吗|有人吗|还在吗)$",
        r"^(早上好|中午好|下午好|晚上好)$",
        r"^(哈喽|hello there|嗨嗨)$",
    )

    for pattern in model_patterns:
        if re.search(pattern, normalized):
            return "model"

    for pattern in identity_patterns:
        if re.search(pattern, normalized):
            return "identity"

    for pattern in capability_patterns:
        if re.search(pattern, normalized):
            return "capability"

    for pattern in subject_patterns:
        if re.search(pattern, normalized):
            return "subject"

    for pattern in greeting_patterns:
        if re.search(pattern, normalized):
            return "greeting"

    return "general"


def meta_agent(state: AgentState) -> dict[str, Any]:
    question = state.get("question", "")
    subject_name = state.get("subject_name", "通用知识")
    subject_description = state.get("subject_description", "")
    intent = _detect_meta_intent(question)
    model_id, model_label, model_provider = _resolve_model_snapshot()

    logger.info(
        f"🪪 元问题 Agent 开始 | intent={intent} | "
        f"subject={subject_name} | question={question[:60]}…"
    )

    capability_lines = [
        "讲解知识点、拆解思路、生成练习题",
        "基于当前学科知识库优先检索回答",
        "记录最近学习主题和薄弱点",
    ]

    if state.get("question_type") == "smalltalk" or intent == "greeting":
        topic = "开场问候"
        thinking = (
            f"你好，我已经在线。你当前正在使用「{subject_name}」这个笔记本，"
            "可以直接问知识点、发题目、让我出练习题，或者问我当前用的模型。"
        )
        steps = [
            f"当前笔记本：{subject_name}",
            "如果你想学概念，可以直接问“什么是 HTTP？”",
            "如果你想刷题，可以直接说“给我出两道数据库索引练习题”。",
        ]
        mistakes = "只发问候语时，我还不知道你具体想学什么；带上主题会更快进入讲解。"
        similar = ["什么是 HTTP？", "给我出两道数据库索引练习题", "你是什么模型？"]
    elif intent == "model":
        topic = "当前对话模型"
        thinking = (
            f"我当前使用的聊天模型是 {model_label}（模型 ID: {model_id}），"
            f"提供方是 {model_provider}。"
        )
        steps = [
            f"当前笔记本：{subject_name}",
            f"当前模型：{model_label}",
            "如果你想换模型，可以在聊天页顶部的模型卡片里切换。",
        ]
        mistakes = "不要把“当前聊天模型”和“底层接入平台”混为一谈。"
        similar = ["你能做什么？", "当前知识库是什么？"]
    elif intent == "identity":
        topic = "助手身份"
        thinking = (
            f"我是一个面向学习场景的多 Agent 助手，当前围绕「{subject_name}」这个笔记本为你服务，"
            f"并由 {model_label} 提供对话能力。"
        )
        steps = [
            "我会先判断你的问题类型，再决定是讲解、出题、复习还是回答助手信息。",
            "如果当前学科有资料，我会优先基于该知识库回答。",
            "如果你问的是模型、能力、当前助手等信息，我会直接回答，不再走知识检索。",
        ]
        mistakes = "如果你想知道的是“当前模型”，直接问“你现在用的是什么模型？”会更准确。"
        similar = ["你是什么模型？", "你能做什么？"]
    elif intent == "capability":
        topic = "助手能力范围"
        thinking = (
            f"我现在最擅长的是围绕「{subject_name}」这个笔记本做学习辅导，"
            "包括讲解、练习、复习和知识库问答。"
        )
        steps = capability_lines + [
            "你也可以上传 PDF、抓取网页，或者让我为学科自动生成基础知识框架。",
        ]
        mistakes = "如果你需要的是‘直接出题’，请明确说“给我出几道题”。"
        similar = ["帮我复习这个知识点", "给我出两道练习题"]
    elif intent == "subject":
        topic = "当前笔记本与知识库"
        thinking = f"你当前正在使用「{subject_name}」这个笔记本。"
        steps = [
            f"当前笔记本：{subject_name}",
            (
                f"当前笔记本简介：{subject_description}"
                if subject_description
                else "当前笔记本暂未设置额外简介。"
            ),
            "如果你切换笔记本，我会切换到对应的知识库上下文。",
        ]
        mistakes = "同一个问题在不同学科助手下，回答依据可能不同。"
        similar = ["你是什么模型？", "你能做什么？"]
    else:
        topic = "助手说明"
        thinking = (
            f"这是一个学习辅导 Agent。你现在使用的是「{subject_name}」笔记本，"
            f"当前对话模型是 {model_label}。"
        )
        steps = [
            "如果你在问模型，我可以直接告诉你当前模型。",
            "如果你在问题目，我会先判断是概念题、解题题、练习题还是复习题。",
            "如果你愿意，也可以直接开始提问具体知识点。",
        ]
        mistakes = "为了让我更准确分类，尽量把问题表达成“讲解”“出题”“复习”“助手信息”之一。"
        similar = ["你是什么模型？", "给我出两道练习题"]

    explanation = {
        "topic": topic,
        "thinking": thinking,
        "steps": steps,
        "mistakes": mistakes,
        "similar": similar,
    }

    return {
        "explanation": explanation,
        "final_answer": thinking,
    }
