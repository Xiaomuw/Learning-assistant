from __future__ import annotations

from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from app.domains.practice.common import (
    OPTION_KEYS,
    extract_mcq_answer_letter,
    format_user_style_instruction,
    normalize_option_rationales,
    parse_mcq_text,
)
from app.domains.practice.llm import get_generation_llm
from app.domains.practice.schemas import McqSolveOutput, QuizOptionOutput
from app.infrastructure.llm.structured import invoke_with_schema, message_to_text

MCQ_SOLVER_SYSTEM_PROMPT = """\
你是一位选择题讲解老师。请从用户原始文本中识别题干与 A/B/C/D 四个选项，
然后判断正确选项，并解释每个选项为什么对或错。

## 当前笔记本
{subject_name}

## 用户风格要求
{user_style_instruction}

## 最近对话上下文
{short_term_context}

## 当前会话摘要
{session_memory_context}

## 用户长期学习记忆
{long_term_context}

## 输出要求
1. parsed_question：清洗后的题干
2. parsed_options：按 A/B/C/D 输出四个选项
3. correct_option：正确答案
4. explanation：完整解析
5. option_rationales：对 A/B/C/D 分别说明对或错
6. topic：本题核心知识点
7. mistakes：本题最容易踩的坑
8. similar：2-3 个相关知识点

请严格只输出 JSON，不要输出 Markdown 或额外说明。格式：
{{"topic":"知识点","parsed_question":"题干","parsed_options":[{{"key":"A","text":"选项A"}},{{"key":"B","text":"选项B"}},{{"key":"C","text":"选项C"}},{{"key":"D","text":"选项D"}}],"correct_option":"A","explanation":"解析","option_rationales":{{"A":"说明","B":"说明","C":"说明","D":"说明"}},"mistakes":"易错点","similar":["相关1","相关2"]}}
"""

MCQ_SOLVER_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", MCQ_SOLVER_SYSTEM_PROMPT),
        ("human", "{question}"),
    ]
)

MCQ_PLAIN_FALLBACK_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是一位选择题老师。请判断用户题目 A/B/C/D 的正确选项。"
            "只输出一句话，必须包含“正确答案是 X”，X 只能是 A/B/C/D，然后给出简短解析。",
        ),
        ("human", "{question}"),
    ]
)


def _known_fact_answer(question: str, parsed_options: list[dict[str, str]]) -> str | None:
    normalized_question = question.lower()
    port_facts = [
        (("https", "默认端口"), "443", "HTTPS 默认端口是 443。"),
        (("http", "默认端口"), "80", "HTTP 默认端口是 80。"),
        (("dns", "默认端口"), "53", "DNS 默认端口是 53。"),
        (("ftp", "默认端口"), "21", "FTP 控制连接默认端口是 21。"),
    ]
    for keywords, expected_text, _reason in port_facts:
        if all(keyword in normalized_question or keyword in question for keyword in keywords):
            for option in parsed_options:
                if expected_text in option.get("text", ""):
                    return option["key"]
    return None


def _build_heuristic_mcq_result(
    payload: dict[str, Any],
    parsed_question: str,
    parsed_options: list[dict[str, str]],
    correct_option: str,
) -> McqSolveOutput:
    option_text = next(
        (option["text"] for option in parsed_options if option["key"] == correct_option),
        "",
    )
    option_rationales = {
        option["key"]: (
            f"这是正确答案，题干所问的默认端口对应 {option_text}。"
            if option["key"] == correct_option
            else "该选项与题干所问的默认端口不匹配。"
        )
        for option in parsed_options
    }
    return McqSolveOutput(
        topic="常见网络协议默认端口",
        parsed_question=parsed_question,
        parsed_options=[QuizOptionOutput(**option) for option in parsed_options],
        correct_option=correct_option,  # type: ignore[arg-type]
        explanation=f"正确答案是 {correct_option}。这类题要把协议名称和默认端口对应起来记忆。",
        option_rationales=option_rationales,
        mistakes="容易把 HTTP 的 80 和 HTTPS 的 443 混淆。",
        similar=["HTTP 默认端口", "HTTPS 默认端口", "DNS 默认端口"],
    )


def _invoke_mcq_plain_fallback(
    payload: dict[str, Any],
    *,
    model_name: str | None,
    original_error: Exception,
) -> McqSolveOutput:
    parsed_question, parsed_options = parse_mcq_text(str(payload.get("question", "") or ""))
    if len(parsed_options) != 4:
        raise original_error

    heuristic_answer = _known_fact_answer(str(payload.get("question", "") or ""), parsed_options)
    if heuristic_answer:
        return _build_heuristic_mcq_result(
            payload,
            parsed_question,
            parsed_options,
            heuristic_answer,
        )

    response = (
        MCQ_PLAIN_FALLBACK_PROMPT
        | get_generation_llm(
            temperature=0.1,
            model_name=model_name,
            timeout_seconds=10.0,
            max_retries=0,
        )
    ).invoke({"question": payload.get("question", "")})
    raw_text = message_to_text(response)
    correct_option = extract_mcq_answer_letter(raw_text)
    if correct_option not in OPTION_KEYS:
        raise original_error

    option_rationales = {
        option["key"]: (
            "这是本题的正确选项。"
            if option["key"] == correct_option
            else "该选项不是本题的正确答案。"
        )
        for option in parsed_options
    }
    return McqSolveOutput(
        topic=str(payload.get("subject_name", "") or "选择题"),
        parsed_question=parsed_question,
        parsed_options=[QuizOptionOutput(**option) for option in parsed_options],
        correct_option=correct_option,  # type: ignore[arg-type]
        explanation=raw_text[:2000],
        option_rationales=option_rationales,
        mistakes="注意不要只凭熟悉感选项，要回到题干所问的核心概念。",
        similar=["选择题审题", "干扰项辨析"],
    )


def _invoke_mcq_solver_chain(payload: dict[str, Any], *, model_name: str | None = None) -> McqSolveOutput:
    return invoke_with_schema(
        MCQ_SOLVER_PROMPT,
        get_generation_llm(
            temperature=0.1,
            model_name=model_name,
            timeout_seconds=12.0,
            max_retries=0,
        ),
        McqSolveOutput,
        payload,
        model_name=model_name,
    )


def solve_mcq_question(
    *,
    question: str,
    subject_name: str,
    user_style_name: str,
    user_style_prompt: str,
    short_term_context: str,
    session_memory_context: str,
    long_term_context: str,
    model_name: str | None = None,
) -> dict[str, Any]:
    payload = {
        "question": question,
        "subject_name": subject_name,
        "user_style_instruction": format_user_style_instruction(user_style_name, user_style_prompt),
        "short_term_context": short_term_context,
        "session_memory_context": session_memory_context,
        "long_term_context": long_term_context,
    }
    try:
        result = _invoke_mcq_solver_chain(payload, model_name=model_name)
    except Exception as exc:
        logger.warning(f"⚠️ 结构化选择题判题失败，改走文本判题兜底: {exc}")
        result = _invoke_mcq_plain_fallback(
            payload,
            model_name=model_name,
            original_error=exc,
        )

    parsed_options = [{"key": item.key, "text": item.text} for item in result.parsed_options]
    option_rationales = normalize_option_rationales(result.option_rationales)
    correct_option_text = next(
        (item["text"] for item in parsed_options if item["key"] == result.correct_option),
        "",
    )
    explanation = {
        "topic": result.topic,
        "thinking": f"这是一道「{result.topic}」相关选择题，正确答案是 {result.correct_option}。",
        "steps": [
            f"题干：{result.parsed_question}",
            f"正确选项：{result.correct_option}。{correct_option_text}",
            result.explanation,
        ],
        "mistakes": result.mistakes,
        "similar": result.similar,
    }
    lines = [
        f"我先把这道选择题拆开了。正确答案是 {result.correct_option}。",
        result.explanation,
    ]
    for key in OPTION_KEYS:
        rationale = option_rationales.get(key)
        if rationale:
            lines.append(f"{key}：{rationale}")

    return {
        "explanation": explanation,
        "final_answer": "\n".join(lines),
    }
