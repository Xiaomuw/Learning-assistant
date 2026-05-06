"""
Web Search Node
===============
LangGraph-visible Tavily fallback for main Q&A flows.

This node is intentionally separate from ``rag_node`` so Studio, SSE, and the
frontend process panel can show when the graph left local notebook retrieval and
used external search.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

from app.shared.schemas.state import AgentState

_WEB_SEARCH_ELIGIBLE_TYPES = {"concept", "problem", "review", "mcq_problem"}


def _build_tavily_tool_call(
    *,
    question: str,
    success: bool,
    doc_count: int = 0,
    error: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "tavily_web_search",
        "args": {
            "query": question,
            "max_results": 5,
        },
        "success": success,
        "doc_count": doc_count,
        "external": True,
    }
    if error:
        payload["error"] = error
    return payload


def _empty_web_search_result(*, attempted: bool = False, error: str = "") -> dict[str, Any]:
    return {
        "documents": [],
        "attempted": attempted,
        "used": False,
        "tool_call": None,
        "error": error,
    }


def call_tavily_search(question: str, question_type: str) -> dict[str, Any]:
    """
    Run Tavily as a graph-visible external search fallback.

    The return shape is deliberately dict-based because it is copied into
    LangGraph state and eventually SSE events.
    """
    if question_type not in _WEB_SEARCH_ELIGIBLE_TYPES:
        return _empty_web_search_result()

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return {
            "documents": [],
            "attempted": True,
            "used": False,
            "tool_call": _build_tavily_tool_call(
                question=question,
                success=False,
                error="tavily_unconfigured",
            ),
            "error": "tavily_unconfigured",
        }

    try:
        from tavily import TavilyClient  # type: ignore[import]

        client = TavilyClient(api_key=api_key)
        logger.info(f"🌐 web_search_node Tavily 搜索 | question={question[:60]}")
        response = client.search(
            query=question,
            max_results=5,
            search_depth="basic",
            include_answer=True,
            include_raw_content=False,
        )
        results = response.get("results", []) or []
        tavily_answer = response.get("answer", "") or ""

        documents: list[dict[str, Any]] = []
        if tavily_answer.strip():
            documents.append(
                {
                    "content": tavily_answer.strip()[:1200],
                    "metadata": {
                        "source": "tavily_summary",
                        "url": "",
                        "title": f"网络搜索摘要：{question[:40]}",
                        "retrieval_source": "tavily_web",
                    },
                    "score": 0.92,
                    "distance": 0.08,
                }
            )

        for item in results:
            content = str(item.get("content", "") or "").strip()
            if not content:
                continue
            score = float(item.get("score", 0.5) or 0.5)
            documents.append(
                {
                    "content": content[:800],
                    "metadata": {
                        "source": "tavily_web",
                        "url": str(item.get("url", "") or ""),
                        "title": str(item.get("title", "") or ""),
                        "retrieval_source": "tavily_web",
                    },
                    "score": score,
                    "distance": 1.0 - score,
                }
            )

        logger.info(f"🌐 web_search_node Tavily 完成 | 返回 {len(documents)} 条网络文档")
        return {
            "documents": documents,
            "attempted": True,
            "used": bool(documents),
            "tool_call": _build_tavily_tool_call(
                question=question,
                success=True,
                doc_count=len(documents),
            ),
            "error": "",
        }
    except Exception as exc:
        safe_error = type(exc).__name__
        logger.warning(f"⚠️ web_search_node Tavily 搜索失败（不阻断主链路）: {safe_error}")
        return {
            "documents": [],
            "attempted": True,
            "used": False,
            "tool_call": _build_tavily_tool_call(
                question=question,
                success=False,
                error=safe_error,
            ),
            "error": safe_error,
        }


def web_search_agent(state: AgentState) -> dict[str, Any]:
    question = str(
        state.get("contextual_question")
        or state.get("contextual_query")
        or state.get("question")
        or state.get("normalized_question")
        or ""
    ).strip()
    question_type = str(state.get("question_type") or "concept").strip()

    result = call_tavily_search(question, question_type)
    documents = list(result.get("documents") or [])
    tool_call = result.get("tool_call")
    external_tool_calls = list(state.get("external_tool_calls") or [])
    if tool_call:
        external_tool_calls.append(tool_call)

    previous_docs = list(state.get("retrieved_docs") or [])
    retrieved_docs = previous_docs
    rag_ready = bool(state.get("rag_ready", False))
    retrieval_diagnosis = (
        dict(state.get("retrieval_diagnosis") or {})
        if isinstance(state.get("retrieval_diagnosis"), dict)
        else {}
    )

    if documents:
        retrieved_docs = documents + previous_docs
        rag_ready = True
        previous_source_policy = str(state.get("source_policy") or "")
        source_policy = "mixed" if previous_docs and previous_source_policy == "notebook" else "web"
        doc_type_counts = dict(retrieval_diagnosis.get("doc_type_counts") or {})
        doc_type_counts["web"] = doc_type_counts.get("web", 0) + len(documents)
        retrieval_diagnosis = {
            **retrieval_diagnosis,
            "query": retrieval_diagnosis.get("query") or question,
            "hit_count": int(retrieval_diagnosis.get("hit_count") or 0) + len(documents),
            "top_score": max(float(retrieval_diagnosis.get("top_score") or 0.0), 0.92),
            "doc_type_counts": doc_type_counts,
            "diagnosis": "ready",
            "coverage_level": retrieval_diagnosis.get("coverage_level") or "partial",
            "suggested_actions": [],
        }
    else:
        source_policy = str(state.get("source_policy") or "web")

    update: dict[str, Any] = {
        "retrieved_docs": retrieved_docs,
        "contextual_query": state.get("contextual_query") or question,
        "retrieval_diagnosis": retrieval_diagnosis,
        "rag_precomputed": True,
        "rag_ready": rag_ready,
        "external_tool_calls": external_tool_calls,
        "web_search_attempted": bool(result.get("attempted", False)),
        "web_search_used": bool(result.get("used", False)),
        "web_search_error": str(result.get("error", "") or ""),
        "web_search_diagnosis": {
            "attempted": bool(result.get("attempted", False)),
            "used": bool(result.get("used", False)),
            "doc_count": len(documents),
            "error": str(result.get("error", "") or ""),
        },
        "source_policy": source_policy,
    }

    if not documents and result.get("attempted"):
        update["graph_warnings"] = [
            f"tavily_web_search did not provide usable context"
            + (f" ({result['error']})" if result.get("error") else ".")
        ]

    return update
