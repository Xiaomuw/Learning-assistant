from __future__ import annotations

import ast
import operator
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domains.qa.schemas import AnswerSchema


_ALLOWED_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def classify_lightweight_answer_intent(question: str) -> str:
    """Classify small, deterministic turns before involving a generative model."""

    text = " ".join(str(question or "").split()).strip()
    if not text:
        return "general"
    if is_arithmetic_practice_generation_request(text):
        return "practice_generation"
    if solve_simple_arithmetic(text) is not None:
        return "simple_fact"
    if any(term in text for term in ("一步步", "教我", "不会", "讲详细", "详细解释")):
        return "tutoring"
    if any(term in text for term in ("解释", "为什么", "原理", "怎么理解")):
        return "explanation"
    return "general"


def build_lightweight_answer_schema(question: str) -> AnswerSchema | None:
    intent = classify_lightweight_answer_intent(question)
    if intent == "simple_fact":
        direct = build_simple_arithmetic_answer(question)
        if not direct:
            return None
        return AnswerSchema(
            topic="简单计算",
            thinking=direct,
            steps=[direct],
            mistakes="简单计算题直接给出结果即可，不需要展开到算法或数据结构。",
            similar=["继续做一道口算题", "让我帮你生成几道练习"],
            final_answer=direct,
        )
    if intent == "practice_generation":
        return build_arithmetic_practice_answer_schema(question)
    return None


def is_arithmetic_practice_generation_request(question: str) -> bool:
    text = " ".join(str(question or "").split()).strip()
    if not text:
        return False
    has_request = bool(re.search(r"(?:帮我|给我|请)?(?:出|来|生成|给|做).{0,12}(?:几|[一两二三四五六七八九十0-9]+)\s*道", text))
    has_arithmetic = any(term in text for term in ("加减法", "口算", "运算", "加法", "减法"))
    has_practice = any(term in text for term in ("题", "练习", "道", "测验"))
    return has_request and has_arithmetic and has_practice


def build_simple_arithmetic_answer(question: str) -> str | None:
    result = solve_simple_arithmetic(question)
    if result is None:
        return None
    expression = _display_expression(_extract_arithmetic_expression(question))
    if not expression:
        expression = "这道题"
    return f"{expression} = {_format_number(result)}。"


def solve_simple_arithmetic(question: str) -> Decimal | None:
    expression = _extract_arithmetic_expression(question)
    if not expression or not re.search(r"\d", expression) or not re.search(r"[+\-*/]", expression):
        return None
    try:
        parsed = ast.parse(expression, mode="eval")
        value = _eval_arithmetic_ast(parsed.body)
        return Decimal(str(value))
    except (SyntaxError, ValueError, ZeroDivisionError, InvalidOperation):
        return None


def build_arithmetic_practice_answer_schema(question: str) -> AnswerSchema | None:
    if not is_arithmetic_practice_generation_request(question):
        return None
    count = _parse_requested_count(question)
    exercises = _build_arithmetic_exercises(count, max_value=_parse_max_value(question))
    final_answer = "\n".join(f"{index}. {item}" for index, item in enumerate(exercises, start=1))
    return AnswerSchema(
        topic="一百以内加减法练习",
        thinking="下面是符合要求的加减法练习题。",
        steps=[final_answer],
        mistakes="",
        similar=["继续生成同类口算题", "生成带答案的版本"],
        final_answer=final_answer,
    )


def _extract_arithmetic_expression(question: str) -> str:
    text = str(question or "").strip()
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("×", "*").replace("÷", "/")
    text = text.replace("加", "+").replace("减", "-")
    text = re.sub(r"(?:等于|是)\s*(?:多少|几|\?|？)?$", "", text)
    text = re.sub(r"(?:多少|几|\?|？|。|！|!)$", "", text)
    if "=" in text:
        text = text.split("=", 1)[0]
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return ""
    if not re.fullmatch(r"[0-9+\-*/().]+", compact):
        return ""
    return compact


def _eval_arithmetic_ast(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BIN_OPS:
        left = _eval_arithmetic_ast(node.left)
        right = _eval_arithmetic_ast(node.right)
        return Decimal(str(_ALLOWED_BIN_OPS[type(node.op)](left, right)))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY_OPS:
        operand = _eval_arithmetic_ast(node.operand)
        return Decimal(str(_ALLOWED_UNARY_OPS[type(node.op)](operand)))
    raise ValueError("unsupported arithmetic expression")


def _format_number(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f").rstrip("0").rstrip(".")


def _display_expression(expression: str) -> str:
    if not expression:
        return ""
    display = expression.replace("*", " × ").replace("/", " ÷ ")
    display = display.replace("+", " + ").replace("-", " − ")
    display = re.sub(r"\s+", " ", display).strip()
    return display


def _parse_requested_count(question: str) -> int:
    text = str(question or "")
    match = re.search(r"(\d+)\s*道", text)
    if match:
        return max(1, min(10, int(match.group(1))))
    zh_counts = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    match = re.search(r"([一两二三四五六七八九十])\s*道", text)
    if match:
        return max(1, min(10, zh_counts.get(match.group(1), 5)))
    return 5


def _parse_max_value(question: str) -> int:
    text = str(question or "")
    if "一百以内" in text or "100以内" in text or "100 以内" in text:
        return 100
    return 100


def _build_arithmetic_exercises(count: int, *, max_value: int) -> list[str]:
    templates = [
        (25, "+", 13),
        (47, "+", 28),
        (61, "+", 39),
        (88, "−", 35),
        (72, "−", 48),
        (36, "+", 57),
        (94, "−", 26),
        (18, "+", 64),
        (83, "−", 29),
        (45, "+", 38),
    ]
    exercises: list[str] = []
    for left, op, right in templates:
        if left <= max_value and right <= max_value:
            exercises.append(f"{left} {op} {right} = ?")
        if len(exercises) >= count:
            break
    return exercises
