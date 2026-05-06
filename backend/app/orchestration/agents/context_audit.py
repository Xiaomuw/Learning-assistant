"""
Context Audit Node
==================
审查 notebook 检索结果是否真的能回答用户问题。

该节点把 raw_retrieved_docs 与 verified_context 分离，保证主回答和
确定性 fallback 不会直接消费未审查的检索命中。
"""

from __future__ import annotations

from typing import Any

from app.services.rag.retriever import extract_query_key_terms, filter_relevant_documents
from app.shared.schemas.contracts import RetrievedDocument
from app.shared.schemas.state import AgentState

CONTEXT_AUDIT_PROMPT = """\
你是 RAG 检索结果审查器。请判断 retrieved_context 是否能直接回答 user_question。
不要回答用户问题，只做相关度与可用性判断。

输入：
- user_question: {user_question}
- rewritten_question: {rewritten_question}
- topic: {topic}
- notebook_policy: skip/optional/required/strict
- retrieved_context: {context}

判断标准：
1. context 必须包含或明确讨论 user_question 的核心实体、同义词或主题。
2. context 必须能支持回答问题，而不是只提供泛泛学习建议。
3. 如果用户问“什么是 HTTP”，context 至少应讨论 HTTP、Web 协议、请求响应、浏览器服务器通信等相关内容。
4. 如果 context 与 topic 无关，即使检索分数高，也必须判为不可用。
5. 如果 notebook_policy=strict 且 context 不足，应判不可用并说明资料不足。
6. 不允许因为“检索命中”就判可用。

输出 JSON：
{
  "usable": true/false,
  "score": 0.0-1.0,
  "decision": "keep" | "discard" | "partial",
  "reason": "简短原因",
  "matched_terms": ["..."],
  "missing_terms": ["..."],
  "can_answer_question": true/false
}
"""

KEEP_THRESHOLD = 0.70
PARTIAL_THRESHOLD = 0.55

_GENERIC_ADVICE_MARKERS = (
    "如何提出",
    "提问",
    "问题越具体",
    "更可检索",
    "学习助手提问",
    "上传资料",
    "补充资料",
)


def _to_retrieved_document(raw: dict[str, Any]) -> RetrievedDocument | None:
    try:
        return RetrievedDocument.model_validate(raw)
    except Exception:
        return None


def _doc_text(doc: dict[str, Any]) -> str:
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    metadata_text = " ".join(str(value) for value in metadata.values() if value)
    return f"{doc.get('content', '')}\n{metadata_text}".lower()


def _matched_terms(docs: list[dict[str, Any]], terms: list[str]) -> list[str]:
    matched: list[str] = []
    for term in terms:
        if any(term.lower() in _doc_text(doc) for doc in docs):
            matched.append(term)
    return matched


def _looks_like_generic_advice(doc: dict[str, Any]) -> bool:
    text = str(doc.get("content", "") or "")
    return any(marker in text for marker in _GENERIC_ADVICE_MARKERS)


def _build_audit_payload(
    *,
    query: str,
    raw_docs: list[dict[str, Any]],
    verified_docs: list[dict[str, Any]],
    relevance: dict[str, Any],
    notebook_policy: str,
) -> dict[str, Any]:
    key_terms = [str(item) for item in list(relevance.get("key_terms") or extract_query_key_terms(query))]
    matched = _matched_terms(verified_docs, key_terms)
    missing = [term for term in key_terms if term not in matched]
    top_score = float(relevance.get("top_score") or 0.0)
    verified_count = len(verified_docs)
    raw_count = len(raw_docs)
    discarded_count = max(0, raw_count - verified_count)
    relevance_reason = str(relevance.get("reason", "") or "")

    has_generic_advice_only = bool(raw_docs) and all(_looks_like_generic_advice(doc) for doc in raw_docs)
    if verified_count and top_score >= KEEP_THRESHOLD:
        decision = "keep"
        usable = True
        reason = "verified_context_ready"
        can_answer = True
        score = max(KEEP_THRESHOLD, top_score)
    elif raw_count and top_score >= PARTIAL_THRESHOLD and relevance_reason != "no_core_term_overlap":
        decision = "partial"
        usable = False
        reason = "partial_context_not_enough_for_answer"
        can_answer = False
        score = min(top_score, KEEP_THRESHOLD - 0.01)
    else:
        decision = "discard"
        usable = False
        can_answer = False
        score = min(top_score, PARTIAL_THRESHOLD - 0.01) if raw_count else 0.0
        if has_generic_advice_only:
            reason = "generic_advice_not_answer_context"
        elif relevance_reason == "no_core_term_overlap":
            reason = "no_core_entity_overlap"
        elif not raw_count:
            reason = "no_retrieved_context"
        else:
            reason = relevance_reason or "low_relevance"

    if notebook_policy == "strict" and not usable:
        reason = "notebook_context_insufficient"

    return {
        "usable": usable,
        "score": round(float(score), 4),
        "decision": decision,
        "reason": reason,
        "matched_terms": matched,
        "missing_terms": missing,
        "can_answer_question": can_answer,
        "raw_count": raw_count,
        "verified_count": verified_count,
        "discarded_count": discarded_count,
    }


def _format_notebook_context(docs: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, doc in enumerate(docs, start=1):
        content = str(doc.get("content", "") or "").strip()
        if not content:
            continue
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        title = str(metadata.get("title") or metadata.get("source") or metadata.get("doc_type") or "").strip()
        prefix = f"[{index}] {title}\n" if title else f"[{index}]\n"
        parts.append(f"{prefix}{content}")
    return "\n\n".join(parts)


def _answer_mode_for_audit(*, notebook_policy: str, usable: bool) -> str:
    if usable:
        return "notebook_grounded" if notebook_policy == "strict" else "hybrid"
    if notebook_policy == "strict":
        return "insufficient_notebook"
    return "general_teaching"


def context_audit_agent(state: AgentState) -> dict[str, Any]:
    question = str(
        state.get("contextual_question")
        or state.get("contextual_query")
        or state.get("question")
        or state.get("normalized_question")
        or ""
    ).strip()
    notebook_policy = str(state.get("notebook_policy") or "optional")
    raw_docs = list(state.get("raw_retrieved_docs") or state.get("retrieved_docs") or [])
    typed_docs = [
        doc
        for doc in (_to_retrieved_document(raw) for raw in raw_docs if isinstance(raw, dict))
        if doc is not None
    ]

    verified_typed, relevance = filter_relevant_documents(
        query=question,
        docs=typed_docs,
        threshold=KEEP_THRESHOLD,
    )
    verified_docs = [doc.model_dump() for doc in verified_typed]
    audit = _build_audit_payload(
        query=question,
        raw_docs=raw_docs,
        verified_docs=verified_docs,
        relevance=dict(relevance),
        notebook_policy=notebook_policy,
    )
    notebook_context = _format_notebook_context(verified_docs)

    retrieval_diagnosis = (
        dict(state.get("retrieval_diagnosis") or {})
        if isinstance(state.get("retrieval_diagnosis"), dict)
        else {}
    )
    retrieval_diagnosis.update(
        {
            "hit_count": len(verified_docs),
            "top_score": audit["score"] if verified_docs else 0.0,
            "diagnosis": "ready" if audit["usable"] else "no_matching_docs",
        }
    )

    return {
        "raw_retrieved_docs": raw_docs,
        "verified_context": verified_docs,
        "retrieved_docs": verified_docs,
        "notebook_retrieved": bool(raw_docs),
        "notebook_context": notebook_context,
        "notebook_required": notebook_policy == "strict",
        "answer_mode": _answer_mode_for_audit(
            notebook_policy=notebook_policy,
            usable=bool(audit["usable"]),
        ),
        "context_audit": audit,
        "retrieval_relevance": relevance,
        "retrieval_diagnosis": retrieval_diagnosis,
        "rag_ready": bool(audit["usable"]),
        "source_policy": "notebook" if audit["usable"] else state.get("source_policy", "none"),
    }
