from __future__ import annotations

import ast
import re
import subprocess
import sys
from typing import Any

from app.shared.schemas.contracts import CodeExecutionResult

_DANGEROUS_PATTERNS = [
    r"\b(import|open|exec|eval|compile|__import__|input)\b",
    r"\b(os|sys|subprocess|socket|requests|urllib|pathlib|shutil)\b",
    r"(__|globals|locals|vars)",
]


def _blocked(code: str) -> bool:
    return any(re.search(pattern, code, flags=re.IGNORECASE) for pattern in _DANGEROUS_PATTERNS)


def _safe_eval_expression(expr: str) -> CodeExecutionResult:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return CodeExecutionResult(executed=False)

    allowed = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Load,
    )
    if not all(isinstance(node, allowed) for node in ast.walk(tree)):
        return CodeExecutionResult(executed=False)
    try:
        value = eval(compile(tree, "<learning-expression>", "eval"), {"__builtins__": {}}, {})
    except Exception as exc:
        return CodeExecutionResult(
            executed=True,
            language="expression",
            success=False,
            stderr=type(exc).__name__,
            hint="计算表达式无法顺利求值，先检查运算符和括号。",
        )
    return CodeExecutionResult(
        executed=True,
        language="expression",
        success=True,
        stdout=str(value)[:500],
    )


def _extract_code(question: str) -> tuple[str, str] | None:
    fenced = re.search(r"```(\w+)?\n(?P<code>.*?)```", question, flags=re.DOTALL)
    if fenced:
        language = (fenced.group(1) or "python").strip().lower()
        return language, fenced.group("code").strip()
    return None


def _run_subprocess(command: list[str], code: str, language: str) -> CodeExecutionResult:
    if _blocked(code):
        return CodeExecutionResult(
            executed=True,
            language=language,
            success=False,
            blocked=True,
            hint="这段代码包含文件、系统、网络或动态执行相关操作，学习验证环境已拒绝运行。",
        )
    try:
        completed = subprocess.run(
            command,
            input=code,
            text=True,
            capture_output=True,
            timeout=2.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CodeExecutionResult(
            executed=True,
            language=language,
            success=False,
            timed_out=True,
            hint="代码运行超时，先检查是否有死循环或等待输入。",
        )
    return CodeExecutionResult(
        executed=True,
        language=language,
        success=completed.returncode == 0,
        stdout=(completed.stdout or "")[:1000],
        stderr=(completed.stderr or "")[:1000],
        hint="" if completed.returncode == 0 else "运行没有通过，先看报错最早出现的位置。",
    )


def execute_code(question: str) -> CodeExecutionResult:
    """Run a very small, restricted verification for code/calculation questions."""
    code_block = _extract_code(question)
    if code_block:
        language, code = code_block
        if language in {"py", "python"}:
            return _run_subprocess([sys.executable, "-I", "-S", "-"], code, "python")
        if language in {"js", "javascript"}:
            return _run_subprocess(["node", "--eval", code], "", "javascript")
        return CodeExecutionResult(
            executed=True,
            language=language,
            success=False,
            blocked=True,
            hint=f"当前只支持 Python/JavaScript 的受限验证，暂不运行 {language}。",
        )

    expr_match = re.search(r"(?P<expr>\d+(?:\s*[+\-*/×÷]\s*\d+)+(?:\s*[+\-*/×÷]\s*\d+)*)", question)
    if expr_match:
        expr = expr_match.group("expr").replace("×", "*").replace("÷", "/")
        return _safe_eval_expression(expr)

    return CodeExecutionResult(executed=False)
