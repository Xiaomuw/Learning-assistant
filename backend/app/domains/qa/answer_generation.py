from __future__ import annotations

from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.domains.qa.prompts import (
    MANUAL_SCHEMA_PROMPT,
    PLAIN_ANSWER_PROMPT,
    REPAIR_PROMPT,
    STRUCTURED_ANSWER_PROMPT,
    build_answer_prompt_payload,
    build_plain_answer_prompt_payload,
    build_tool_system_message,
    message_to_text,
)
from app.domains.qa.schemas import AgentRequest, AnswerSchema
from app.infrastructure.llm.structured import invoke_with_schema, validate_schema_output
from app.shared.schemas.model_profile import ModelProfile

# 这些类型走轻量直接回复，不走结构化 AnswerSchema
_PLAIN_ANSWER_TYPES = {"smalltalk", "meta"}


def generate_structured_answer(
    *,
    request: AgentRequest,
    conversation: list[Any],
    model_profile: ModelProfile,
    get_llm: Callable[..., Any],
) -> AnswerSchema | str | dict[str, Any]:
    """生成结构化答案，payload 中已注入 question_type 对应的 style_instruction"""
    prompt_payload = build_answer_prompt_payload(request, conversation)

    if model_profile.supports_structured_output:
        try:
            return invoke_with_schema(
                STRUCTURED_ANSWER_PROMPT,
                get_llm(temperature=0.2),
                AnswerSchema,
                prompt_payload,
                model_name=model_profile.model_id,
            )
        except Exception as exc:
            logger.warning(f"⚠️ 结构化答案生成失败，改走 JSON 文本输出: {exc}")

    return invoke_with_schema(
        MANUAL_SCHEMA_PROMPT,
        get_llm(temperature=0.2),
        AnswerSchema,
        prompt_payload,
        model_name=model_profile.model_id,
        prefer_native=False,
    )


def generate_plain_answer(
    *,
    request: AgentRequest,
    get_llm: Callable[..., Any],
) -> str:
    """
    生成直接回复文本。
    - smalltalk / meta：使用专用轻量 prompt，自然对话式回复，不套 AnswerSchema 结构
    - 其他类型：附带问题类型上下文，引导模型按策略回复
    """
    if request.question_type in _PLAIN_ANSWER_TYPES:
        # 轻量直接回复：不套结构，自然语言
        response = (PLAIN_ANSWER_PROMPT | get_llm(temperature=0.5)).invoke(
            build_plain_answer_prompt_payload(request)
        )
        return message_to_text(response)

    # 其他类型（兜底 fallback）：附带类型指引
    response = get_llm(temperature=0.3).invoke(
        [
            SystemMessage(content=build_tool_system_message(request)),
            HumanMessage(
                content=(
                    f"问题类型：{request.question_type}\n"
                    f"请直接回答这个问题，并保持教学友好：{request.question}"
                )
            ),
        ]
    )
    return message_to_text(response)


def repair_structured_output(
    *,
    raw_output: Any,
    model_profile: ModelProfile,
    get_llm: Callable[..., Any],
) -> AnswerSchema | None:
    raw_text = message_to_text(raw_output)
    if not raw_text.strip():
        return None

    try:
        if model_profile.supports_structured_output:
            return invoke_with_schema(
                REPAIR_PROMPT,
                get_llm(temperature=0),
                AnswerSchema,
                {"raw_output": raw_text},
                model_name=model_profile.model_id,
            )

        response = (REPAIR_PROMPT | get_llm(temperature=0)).invoke({"raw_output": raw_text})
        return validate_schema_output(response, AnswerSchema)
    except Exception:
        return None
