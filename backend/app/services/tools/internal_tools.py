from __future__ import annotations

from typing import Any

from app.domains.memory.long_term import build_long_term_context
from app.domains.memory.session_summary import build_session_memory_context
from app.infrastructure.db.repositories.practice import list_practice_recommendation_records
from app.infrastructure.db.repositories.users import get_user_memory_record
from app.services.rag.retriever import diagnose_retrieval, get_retrieval_contextual_query, retrieve
from app.shared.schemas.contracts import PracticeRecommendation
from app.shared.schemas.qa_runtime import AgentRequest


def search_notebook_context(
    agent_request: AgentRequest,
    args: dict[str, Any],
) -> dict[str, Any]:
    query = str(args.get("query", "") or agent_request.question).strip()
    top_k = int(args.get("top_k", 4) or 4)
    contextual_query = get_retrieval_contextual_query(
        query,
        agent_request.short_term_messages,
        agent_request.session_memory,
        agent_request.memory,
    )
    docs = retrieve(
        query=contextual_query,
        top_k=top_k,
        subject_id=agent_request.subject_id,
        min_score=0.15,
        user_id=agent_request.user_id,
    )
    retrieval_diagnosis = diagnose_retrieval(
        query=contextual_query,
        docs=docs,
        subject_id=agent_request.subject_id,
        user_id=agent_request.user_id,
        min_ready_score=0.5,
    )
    return {
        "query": query,
        "contextual_query": contextual_query,
        "doc_count": len(docs),
        "retrieval_diagnosis": retrieval_diagnosis.model_dump(),
        "documents": [
            {
                "content": doc.content[:800],
                "metadata": doc.metadata,
                "distance": doc.distance,
                "score": doc.score,
            }
            for doc in docs
        ],
    }


def get_session_summary(
    agent_request: AgentRequest,
    args: dict[str, Any],
) -> dict[str, Any]:
    include_open_loops = bool(args.get("include_open_loops", True))
    payload = {
        "summary_text": agent_request.session_memory.get("summary_text", ""),
        "active_topic": agent_request.session_memory.get("active_topic", ""),
        "current_goal": agent_request.session_memory.get("current_goal", ""),
        "resolved_points": list(agent_request.session_memory.get("resolved_points", []) or []),
        "session_memory_context": build_session_memory_context(agent_request.session_memory),
    }
    if include_open_loops:
        payload["open_loops"] = list(agent_request.session_memory.get("open_loops", []) or [])
    return payload


def get_user_learning_profile(
    agent_request: AgentRequest,
    args: dict[str, Any],
) -> dict[str, Any]:
    return {
        "focus": str(args.get("focus", "overview") or "overview"),
        "weak_points": list(agent_request.memory.get("weak_points", []) or []),
        "recent_topics": list(agent_request.memory.get("recent_topics", []) or []),
        "error_count": dict(agent_request.memory.get("error_count", {}) or {}),
        "long_term_context": build_long_term_context(
            {
                "display_name": "",
                "agent_style_name": "",
                "agent_style_prompt": "",
            },
            agent_request.memory,
        ),
    }


def recommend_questions(
    agent_request: AgentRequest,
    args: dict[str, Any],
) -> dict[str, Any]:
    topic = str(args.get("topic", "") or "").strip()
    limit = int(args.get("limit", 3) or 3)
    memory = get_user_memory_record(agent_request.user_id)
    items = [
        PracticeRecommendation.model_validate(item.model_dump())
        for item in list_practice_recommendation_records(
            memory,
            subject_id=agent_request.subject_id,
            limit=max(limit * 2, limit),
        )
    ]
    if topic:
        items = [
            item for item in items
            if topic in item.knowledge_point or topic in item.question
        ]
    return {
        "count": min(limit, len(items)),
        "items": [
            {
                "question_id": item.question_id,
                "question": item.question,
                "knowledge_point": item.knowledge_point,
                "difficulty": item.difficulty,
                "source_name": item.source_name,
                "source_year": item.source_year,
            }
            for item in items[:limit]
        ],
    }
