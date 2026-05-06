"""
Answer Guard Node
=================
LangGraph-visible final answer guard for main Q&A flows.

It prevents low-value "notebook did not match, please ask for general
knowledge" templates from reaching the user for common concept questions.
"""

from __future__ import annotations

from typing import Any

from app.domains.qa.explanation_fallback import _build_general_knowledge_fallback
from app.shared.schemas.state import AgentState

_GENERIC_MARKERS = (
    "什么是",
    "什么叫",
    "解释",
    "介绍",
    "概念",
    "define",
    "what is",
)

_BAD_TEMPLATE_MARKERS = (
    "我没有在当前 notebook 中命中",
    "如果你希望我按通用知识解释",
    "可以直接追问“按通用知识讲一下”",
    "可以直接追问\"按通用知识讲一下\"",
    "补充 notebook 资料",
    "当前 notebook 暂无可用知识库内容",
    "当前 notebook 暂无可检索资料",
    "不能支撑这个问题",
)


def _is_generic_concept_question(question: str) -> bool:
    normalized = question.lower()
    return (
        "http" in normalized
        or "tcp" in normalized
        or "rag" in normalized
        or any(marker in question for marker in _GENERIC_MARKERS)
        or any(marker in normalized for marker in _GENERIC_MARKERS)
    )


def _contains_bad_template(state: AgentState) -> bool:
    explanation = state.get("explanation") if isinstance(state.get("explanation"), dict) else {}
    combined = " ".join(
        [
            str(state.get("final_answer", "") or ""),
            str(explanation.get("thinking", "") or ""),
            " ".join(str(item) for item in (explanation.get("steps", []) or [])),
            str(explanation.get("mistakes", "") or ""),
        ]
    )
    return any(marker in combined for marker in _BAD_TEMPLATE_MARKERS)


def qa_answer_guard_agent(state: AgentState) -> dict[str, Any]:
    question = str(state.get("question") or state.get("normalized_question") or "").strip()
    if str(state.get("notebook_policy") or "") == "strict":
        return {
            "answer_guard_applied": False,
            "answer_guard_reason": "",
        }
    if not question or not _is_generic_concept_question(question) or not _contains_bad_template(state):
        return {
            "answer_guard_applied": False,
            "answer_guard_reason": "",
        }

    fallback = _build_general_knowledge_fallback(
        question,
        state.get("retrieval_diagnosis") if isinstance(state.get("retrieval_diagnosis"), dict) else None,
    )
    reason = "replaced_no_context_template_with_general_concept_answer"
    return {
        "explanation": fallback,
        "final_answer": str(fallback.get("thinking", "") or ""),
        "degraded": True,
        "answer_guard_applied": True,
        "answer_guard_reason": reason,
        "graph_warnings": [f"qa_answer_guard_node {reason}."],
    }
