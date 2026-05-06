from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.domains.qa.capability_tools import (
    NOTEBOOK_RETRIEVE,
    WEB_EXTRACT,
    WEB_SEARCH,
    tool_executor,
    tool_registry,
)
from app.domains.qa.prompts import build_tool_system_message
from app.domains.qa.schemas import AgentRequest, ToolCall
from app.infrastructure.llm.langsmith import trace_run
from app.services.rag.retriever import filter_relevant_documents
from app.shared.schemas.contracts import RetrievedDocument

MAX_TOOL_LOOPS = 3


def run_tool_loop(
    *,
    request: AgentRequest,
    get_llm: Callable[..., Any],
) -> dict[str, Any]:
    with trace_run(
        name="qa_agent.tool_loop",
        run_type="chain",
        inputs={
            "question_length": len(request.question or ""),
            "question_type": request.question_type,
            "subject_id": request.subject_id,
            "max_tool_loops": MAX_TOOL_LOOPS,
        },
        metadata={"subject_id": request.subject_id},
        tags=["qa-runtime", "tool-loop"],
    ) as loop_run:
        available_tools = tool_registry.get_available_tools(
            scope="qa",
            agent_request=request,
        )
        llm = get_llm().bind_tools(available_tools)
        effective_question = str(
            (request.runtime_context or {}).get("contextual_question")
            or request.question
        )
        messages: list[Any] = [
            SystemMessage(content=build_tool_system_message(request)),
            HumanMessage(content=effective_question),
        ]
        tool_call_records: list[dict[str, Any]] = []
        tool_decision_rounds: list[dict[str, Any]] = []
        retrieved_docs: list[dict[str, Any]] = []
        contextual_query = effective_question
        is_rewritten = False
        retrieval_diagnosis: dict[str, Any] = {}
        capability_call_limits = {
            WEB_SEARCH: 0,
            WEB_EXTRACT: 0,
        }

        for round_index in range(1, MAX_TOOL_LOOPS + 1):
            response = llm.invoke(messages)
            messages.append(response)
            raw_tool_calls = list(getattr(response, "tool_calls", []) or [])
            if not raw_tool_calls:
                tool_decision_rounds.append(
                    _build_no_tool_decision_round(
                        round_index=round_index,
                        request=request,
                        had_previous_tools=bool(tool_call_records),
                    )
                )
                source_usage = _infer_source_usage(tool_call_records)
                _finish_tool_loop_trace(
                    loop_run=loop_run,
                    tool_call_records=tool_call_records,
                    tool_decision_rounds=tool_decision_rounds,
                    retrieved_docs=retrieved_docs,
                    contextual_query=contextual_query,
                    is_rewritten=is_rewritten,
                    retrieval_diagnosis=retrieval_diagnosis,
                )
                return {
                    "conversation": messages,
                    "tool_calls": tool_call_records,
                    "tool_decision_rounds": tool_decision_rounds,
                    "reasoning_summary": _summarize_tool_decisions(
                        request=request,
                        tool_decision_rounds=tool_decision_rounds,
                        source_usage=source_usage,
                    ),
                    "source_usage": source_usage,
                    "retrieved_docs": retrieved_docs,
                    "contextual_query": contextual_query,
                    "is_rewritten": is_rewritten,
                    "retrieval_diagnosis": retrieval_diagnosis,
                }

            for raw_call in raw_tool_calls:
                raw_args = raw_call.get("args", {}) or {}
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        raw_args = {"raw_args": raw_args}

                tool_call = ToolCall(
                    name=str(raw_call.get("name", "") or ""),
                    args=dict(raw_args),
                    call_id=str(raw_call.get("id", "") or f"{raw_call.get('name', 'tool')}-{len(tool_call_records) + 1}"),
                )
                definition = tool_registry.get_definition(tool_call.name)
                capability = definition.capability if definition else tool_call.name
                provider = definition.provider if definition else "unknown"

                if capability in capability_call_limits and capability_call_limits[capability] >= 1:
                    error_message = "当前轮次该外部工具能力调用次数已达上限"
                    tool_call_records.append(
                        {
                            "name": tool_call.name,
                            "capability": capability,
                            "provider": provider,
                            "success": False,
                            "error": error_message,
                            "is_external": True,
                        }
                    )
                    messages.append(
                        ToolMessage(
                            content=json.dumps({"error": error_message}, ensure_ascii=False),
                            tool_call_id=tool_call.call_id,
                        )
                    )
                    continue

                result = tool_executor.execute(
                    tool_call,
                    agent_request=request,
                    scope="qa",
                )
                capability = str(result.payload.get("_tool_capability") or capability)
                provider = str(result.payload.get("_tool_provider") or provider)
                if capability in capability_call_limits:
                    capability_call_limits[capability] += 1
                tool_call_records.append(
                    {
                        "name": tool_call.name,
                        "capability": capability,
                        "provider": provider,
                        "success": result.success,
                        "error": result.error,
                        "doc_count": int(result.payload.get("doc_count") or len(result.payload.get("documents") or []))
                        if result.success
                        else 0,
                        "is_external": bool(definition.is_external) if definition else False,
                    }
                )
                if capability == NOTEBOOK_RETRIEVE and result.success:
                    audited_payload = _audit_notebook_tool_payload(
                        payload=dict(result.payload or {}),
                        query=str(tool_call.args.get("query") or effective_question),
                    )
                    result.payload.clear()
                    result.payload.update(audited_payload)
                    if tool_call_records:
                        tool_call_records[-1]["doc_count"] = int(
                            result.payload.get("doc_count")
                            or len(result.payload.get("documents") or [])
                        )
                    retrieved_docs = list(result.payload.get("documents", []) or [])
                    contextual_query = str(result.payload.get("contextual_query", contextual_query) or contextual_query)
                    is_rewritten = contextual_query != request.question
                    retrieval_diagnosis = dict(result.payload.get("retrieval_diagnosis") or {})
                elif capability == WEB_SEARCH and result.success:
                    web_docs = list(result.payload.get("documents", []) or [])
                    for doc in web_docs:
                        if isinstance(doc.get("metadata"), dict):
                            doc["metadata"]["retrieval_source"] = "web"
                            doc["metadata"]["provider"] = provider
                    retrieved_docs = [*retrieved_docs, *web_docs]
                    contextual_query = str(result.payload.get("query", contextual_query) or contextual_query)
                    is_rewritten = contextual_query != request.question
                elif capability == WEB_EXTRACT and result.success:
                    additional_docs = list(result.payload.get("documents", []) or [])
                    if additional_docs:
                        retrieved_docs = [*retrieved_docs, *additional_docs]

                tool_payload = result.payload if result.success else {"error": result.error or "工具执行失败"}
                tool_decision_rounds.append(
                    _build_tool_decision_round(
                        round_index=round_index,
                        tool_call=tool_call,
                        result_payload=tool_payload,
                        success=result.success,
                        error=result.error,
                        is_external=bool(definition.is_external) if definition else False,
                        capability=capability,
                        provider=provider,
                    )
                )
                messages.append(
                    ToolMessage(
                        content=json.dumps(tool_payload, ensure_ascii=False),
                        tool_call_id=tool_call.call_id,
                    )
                )

        raise RuntimeError("tool calling 超过最大循环次数")


def _finish_tool_loop_trace(
    *,
    loop_run: Any,
    tool_call_records: list[dict[str, Any]],
    tool_decision_rounds: list[dict[str, Any]],
    retrieved_docs: list[dict[str, Any]],
    contextual_query: str,
    is_rewritten: bool,
    retrieval_diagnosis: dict[str, Any],
) -> None:
    web_records = [
        item
        for item in tool_call_records
        if str(item.get("capability") or item.get("name") or "") in {WEB_SEARCH, WEB_EXTRACT}
    ]
    notebook_records = [
        item
        for item in tool_call_records
        if str(item.get("capability") or item.get("name") or "") == NOTEBOOK_RETRIEVE
    ]
    loop_run.metadata.update(
        {
            "tool_calls_count": len(tool_call_records),
            "contextual_query": contextual_query,
            "is_rewritten": is_rewritten,
            "retrieval_diagnosis": retrieval_diagnosis.get("diagnosis", ""),
            "used_notebook": any(bool(item.get("success")) for item in notebook_records),
            "used_web_search": any(bool(item.get("success")) for item in web_records),
            "web_tool_providers": sorted(
                set(str(item.get("provider") or "web") for item in web_records if item.get("provider"))
            ),
            "external_tool_count": len(web_records),
            "tool_decision_rounds_count": len(tool_decision_rounds),
            "tool_degraded": any(not bool(item.get("success")) for item in tool_call_records),
        }
    )
    loop_run.end(
        outputs={
            "tool_calls_count": len(tool_call_records),
            "retrieved_docs_count": len(retrieved_docs),
            "contextual_query": contextual_query,
            "is_rewritten": is_rewritten,
            "retrieval_diagnosis": retrieval_diagnosis,
            "used_notebook": any(bool(item.get("success")) for item in notebook_records),
            "used_web_search": any(bool(item.get("success")) for item in web_records),
            "web_tool_providers": sorted(
                set(str(item.get("provider") or "web") for item in web_records if item.get("provider"))
            ),
            "tool_decision_rounds": tool_decision_rounds,
        }
    )


def _audit_notebook_tool_payload(*, payload: dict[str, Any], query: str) -> dict[str, Any]:
    raw_docs = list(payload.get("documents") or [])
    typed_docs: list[RetrievedDocument] = []
    for raw in raw_docs:
        if not isinstance(raw, dict):
            continue
        try:
            typed_docs.append(RetrievedDocument.model_validate(raw))
        except Exception:
            continue
    verified_docs, relevance = filter_relevant_documents(
        query=query,
        docs=typed_docs,
        threshold=0.70,
    )
    verified_payload = [doc.model_dump() for doc in verified_docs]
    discarded_count = max(0, len(raw_docs) - len(verified_payload))
    audit = {
        "usable": bool(verified_payload),
        "raw_count": len(raw_docs),
        "verified_count": len(verified_payload),
        "discarded_count": discarded_count,
        "reason": "verified_context_ready"
        if verified_payload
        else str(relevance.get("reason") or "low_relevance"),
        "score": float(relevance.get("top_score") or 0.0) if verified_payload else 0.0,
    }
    next_payload = dict(payload)
    next_payload["raw_doc_count"] = len(raw_docs)
    next_payload["doc_count"] = len(verified_payload)
    next_payload["documents"] = verified_payload
    next_payload["context_audit"] = audit
    diagnosis = (
        dict(next_payload.get("retrieval_diagnosis") or {})
        if isinstance(next_payload.get("retrieval_diagnosis"), dict)
        else {}
    )
    diagnosis["hit_count"] = len(verified_payload)
    diagnosis["diagnosis"] = "ready" if verified_payload else "no_matching_docs"
    next_payload["retrieval_diagnosis"] = diagnosis
    return next_payload


def _build_no_tool_decision_round(
    *,
    round_index: int,
    request: AgentRequest,
    had_previous_tools: bool,
) -> dict[str, Any]:
    search_policy = str((request.runtime_context or {}).get("search_policy") or "forbidden")
    notebook_policy = str((request.runtime_context or {}).get("notebook_policy") or "skip")
    if had_previous_tools:
        reason = "工具结果已经足够，继续生成最终回答。"
    elif search_policy == "required":
        reason = "模型未请求工具；将按当前可用上下文生成回答。"
    elif notebook_policy == "skip":
        reason = "判断为可直接讲解的问题，未使用 notebook。"
    else:
        reason = "判断当前问题可先由模型直接回答，工具作为备用。"
    return {
        "round": round_index,
        "decision": "direct_answer",
        "tool": "none",
        "reason": reason,
        "result": "no_tool_call",
    }


def _build_tool_decision_round(
    *,
    round_index: int,
    tool_call: ToolCall,
    result_payload: dict[str, Any],
    success: bool,
    error: str,
    is_external: bool,
    capability: str,
    provider: str,
) -> dict[str, Any]:
    doc_count = int(result_payload.get("doc_count") or len(result_payload.get("documents") or []))
    if success and doc_count:
        result = f"获得 {doc_count} 条可用参考"
    elif success:
        result = "未获得可用参考"
    else:
        result = error or "工具调用失败"
    if capability == NOTEBOOK_RETRIEVE:
        reason = "按需查看用户 notebook 是否有辅助资料。"
    elif capability in {WEB_SEARCH, WEB_EXTRACT}:
        reason = "按需补充最新、官网、来源或外部事实。"
    else:
        reason = "按需读取学习上下文或推荐信息。"
    return {
        "round": round_index,
        "decision": "use_tool",
        "tool": capability,
        "provider": provider,
        "reason": reason,
        "result": result,
        "success": success,
        "is_external": is_external,
    }


def _infer_source_usage(tool_call_records: list[dict[str, Any]]) -> str:
    used_notebook = any(
        item.get("capability") == NOTEBOOK_RETRIEVE
        and bool(item.get("success"))
        and int(item.get("doc_count") or 0) > 0
        for item in tool_call_records
    )
    used_web = any(
        item.get("capability") in {WEB_SEARCH, WEB_EXTRACT}
        and bool(item.get("success"))
        and int(item.get("doc_count") or 0) > 0
        for item in tool_call_records
    )
    if used_notebook and used_web:
        return "mixed"
    if used_web:
        return "web"
    if used_notebook:
        return "notebook"
    return "model"


def _summarize_tool_decisions(
    *,
    request: AgentRequest,
    tool_decision_rounds: list[dict[str, Any]],
    source_usage: str,
) -> str:
    if not tool_decision_rounds:
        return ""
    if source_usage == "model":
        return "模型判断本轮可以直接回答，未调用 notebook 或联网搜索。"
    used_tools = [
        str(item.get("tool") or "")
        for item in tool_decision_rounds
        if str(item.get("tool") or "") not in {"", "none"}
    ]
    label_map = {
        NOTEBOOK_RETRIEVE: "notebook",
        WEB_SEARCH: "网络搜索",
        WEB_EXTRACT: "网页读取",
        "session_summary": "会话摘要",
        "learning_profile": "学习画像",
        "question_recommend": "推荐题目",
    }
    labels = [label_map.get(tool, tool) for tool in used_tools]
    unique_labels = list(dict.fromkeys(label for label in labels if label))
    if unique_labels:
        return f"模型按需调用了{'、'.join(unique_labels)}，并基于可用结果生成回答。"
    return "模型完成了工具决策循环，并生成最终回答。"
