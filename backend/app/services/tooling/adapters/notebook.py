from __future__ import annotations

import time
from typing import Any

from app.services.rag.rag_service import retrieve_context
from app.services.tooling.schemas import ToolExecutionRequest, ToolRegistration, ToolRiskLevel
from app.shared.schemas.agent_graphs import ConceptRef, EvidenceChunk, ToolCapability, ToolResult, ToolStatus


class NotebookRetrieveAdapter:
    """Notebook provider for the generic ``notebook_retrieve`` capability."""

    registration = ToolRegistration(
        tool_id="notebook_retrieve:pgvector",
        provider="notebook",
        capability=ToolCapability.NOTEBOOK_RETRIEVE,
        description="Retrieve verified notebook context through the RAG service.",
        enabled=True,
        risk_level=ToolRiskLevel.LOW,
    )

    def invoke(self, request: ToolExecutionRequest) -> ToolResult:
        started = time.perf_counter()
        query = str(request.input.get("query") or request.input_summary or "").strip()
        subject_id = str(
            request.input.get("subject_id")
            or request.input.get("notebook_id")
            or request.runtime_context.get("subject_id")
            or request.runtime_context.get("notebook_id")
            or ""
        ).strip() or None
        user_id = str(request.input.get("user_id") or request.user_id or "").strip() or None
        concept_id = str(request.input.get("concept_id") or request.runtime_context.get("concept_id") or "").strip() or None
        topic_id = str(request.input.get("topic_id") or request.runtime_context.get("topic_id") or "").strip() or None
        top_k = _bounded_int(request.input.get("top_k"), default=5, low=1, high=10)
        min_score = _bounded_float(request.input.get("min_score"), default=0.65, low=0.0, high=1.0)
        try:
            result = retrieve_context(
                question=query,
                subject_id=subject_id,
                user_id=user_id,
                top_k=top_k,
                min_score=min_score,
                memory=_dict_or_empty(request.runtime_context.get("memory")),
                short_term_messages=list(request.runtime_context.get("short_term_messages") or []),
                session_memory=_dict_or_empty(request.runtime_context.get("session_memory")),
                concept_id=concept_id,
                topic_id=topic_id,
            )
            evidence = [
                EvidenceChunk(
                    id=doc.doc_id or f"notebook:{index}",
                    source_type="notebook",
                    source_id=str(doc.metadata.get("source_id") or doc.metadata.get("source") or doc.doc_id or ""),
                    text=doc.content,
                    metadata={
                        **dict(doc.metadata or {}),
                        "diagnosis": result.diagnosis.diagnosis,
                        "contextual_query": result.contextual_query,
                    },
                    score=float(doc.score or 0.0),
                    concepts=_concepts_from_document(doc.metadata, query),
                )
                for index, doc in enumerate(result.docs, start=1)
            ]
            output: dict[str, Any] = {
                "raw_count": len(result.raw_docs),
                "verified_count": len(result.docs),
                "diagnosis": result.diagnosis.diagnosis,
                "top_score": result.diagnosis.top_score,
                "rag_ready": result.rag_ready,
                "relevance": {
                    "kept_count": result.relevance.get("kept_count"),
                    "discarded_count": result.relevance.get("discarded_count"),
                    "reason": result.relevance.get("reason"),
                },
            }
            status = ToolStatus.SUCCESS
            error = ""
        except Exception as exc:
            evidence = []
            output = {"raw_count": 0, "verified_count": 0, "diagnosis": "tool_error"}
            status = ToolStatus.ERROR
            error = exc.__class__.__name__

        return ToolResult(
            tool_id=self.registration.tool_id,
            provider=self.registration.provider,
            capability=self.registration.capability,
            status=status,
            input_summary=query,
            output=output,
            evidence=evidence,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=error,
        )


def _bounded_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _bounded_float(value: Any, *, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _concepts_from_query(query: str) -> list[ConceptRef]:
    topic = query.strip(" ：:，,。.!！?？")[:80]
    if not topic:
        return []
    return [ConceptRef(concept_id=topic.lower().replace(" ", "-")[:64] or topic, name=topic, confidence=0.5, source="query")]


def _concepts_from_document(metadata: dict[str, Any], query: str) -> list[ConceptRef]:
    concept_id = str((metadata or {}).get("concept_id") or "").strip()
    concept_name = str((metadata or {}).get("concept_name") or "").strip()
    if concept_id:
        return [
            ConceptRef(
                concept_id=concept_id,
                name=concept_name or concept_id,
                confidence=0.9,
                source="kb_metadata",
            )
        ]
    return _concepts_from_query(query)
