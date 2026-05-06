"""
RAG Node
========
LangGraph-visible retrieval node for main Q&A flows.

The node retrieves notebook context and diagnostics only. Final answer generation
stays in qa_agent_node so the graph remains readable without fragmenting QA.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.services.rag.rag_service import retrieve_context
from app.shared.schemas.state import AgentState


def rag_agent(state: AgentState) -> dict[str, Any]:
    question = str(
        state.get("contextual_question")
        or state.get("question")
        or state.get("normalized_question")
        or ""
    ).strip()
    subject_id = str(state.get("subject_id") or "general")
    user_id = str(state.get("user_id") or "").strip()
    notebook_policy = str(state.get("notebook_policy") or "optional").strip()
    search_policy = str(state.get("search_policy") or "forbidden").strip()
    notebook_required = notebook_policy == "strict"
    try:
        result = retrieve_context(
            question=question,
            subject_id=subject_id,
            user_id=user_id or None,
            memory=dict(state.get("memory") or {}),
            short_term_messages=list(state.get("short_term_messages") or []),
            session_memory=dict(state.get("session_memory") or {}),
            top_k=5,
            min_score=0.65,
        )
        logger.info(
            f"🔎 rag_node 完成 | subject={subject_id} | "
            f"raw_hits={len(result.raw_docs)} | preliminary_hits={len(result.docs)} | "
            f"diagnosis={result.diagnosis.diagnosis}"
        )
        warning = ""
        if result.diagnosis.diagnosis != "ready":
            warning = f"rag_node diagnosis={result.diagnosis.diagnosis}"

        raw_retrieved_docs = [doc.model_dump() for doc in result.raw_docs]
        preliminary_docs = [doc.model_dump() for doc in result.docs]
        retrieval_diagnosis = result.diagnosis.model_dump()
        relevance = dict(result.relevance or {})
        used_keyword_fallback = any(
            isinstance(doc.get("metadata"), dict)
            and doc["metadata"].get("retrieval_source") == "keyword_fallback"
            for doc in raw_retrieved_docs
        )

        update: dict[str, Any] = {
            "raw_retrieved_docs": raw_retrieved_docs,
            "verified_context": [],
            "retrieved_docs": [],
            "notebook_retrieved": bool(raw_retrieved_docs),
            "notebook_context": "",
            "contextual_query": result.contextual_query,
            "is_rewritten": result.is_rewritten,
            "retrieval_diagnosis": retrieval_diagnosis,
            "retrieval_relevance": relevance,
            "rag_precomputed": True,
            "rag_ready": False,
            "notebook_required": notebook_required,
            "answer_mode": "insufficient_notebook" if notebook_required else "general_teaching",
            "web_search_required": (
                not preliminary_docs
                and not notebook_required
                and search_policy in {"allowed", "required"}
            ),
            "source_policy": state.get("source_policy", "none"),
        }
        if not preliminary_docs and relevance.get("reason") == "no_core_term_overlap":
            warning = "rag_node discarded low-relevance notebook context after key-term filtering"
        if used_keyword_fallback:
            warning = "rag_node used keyword_fallback because vector search was unavailable"
        if warning:
            update["rag_warning"] = warning
            update["graph_warnings"] = [warning]
        return update

    except Exception as exc:
        logger.warning(f"⚠️ rag_node 检索失败，已降级为无 RAG 上下文: {type(exc).__name__}")
        warning = f"rag_node failed with {type(exc).__name__}; qa_agent_node will continue without RAG context."

        return {
            "raw_retrieved_docs": [],
            "verified_context": [],
            "retrieved_docs": [],
            "notebook_retrieved": False,
            "notebook_context": "",
            "contextual_query": question,
            "is_rewritten": False,
            "retrieval_diagnosis": {
                "query": question,
                "hit_count": 0,
                "top_score": 0.0,
                "doc_type_counts": {},
                "diagnosis": "no_matching_docs",
                "coverage_level": "empty",
                "suggested_actions": ["稍后重试检索，或先补充 notebook 资料。"],
            },
            "retrieval_relevance": {
                "query": question,
                "raw_count": 0,
                "kept_count": 0,
                "reason": "retrieval_failed",
            },
            "rag_precomputed": True,
            "rag_ready": False,
            "notebook_required": notebook_required,
            "answer_mode": "insufficient_notebook" if notebook_required else "general_teaching",
            "rag_warning": warning,
            "web_search_required": (
                not notebook_required
                and search_policy in {"allowed", "required"}
            ),
            "graph_warnings": [warning],
        }
