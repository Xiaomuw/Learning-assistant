from __future__ import annotations

import time
import os
from typing import Any

from app.application.chat.answer_cleaning import (
    clean_display_answer,
    clean_display_steps,
    compose_display_answer,
    should_preserve_notebook_notice,
)
from app.domains.practice.service import normalize_quiz_item
from app.shared.markdown_cleaning import strip_markdown_artifacts, strip_markdown_list
from app.shared.schemas.contracts import ExplanationPayload

QUESTION_TYPE_LABELS = {
    "concept": "概念理解",
    "problem": "解题辅导",
    "compare": "概念比较",
    "application": "应用场景",
    "practice": "练习出题",
    "review": "复习巩固",
    "meta": "助手信息",
    "smalltalk": "寒暄对话",
    "mcq_problem": "选择题判题",
}

ROUTE_LABELS = {
    "fast": "快速回答",
    "explain": "教学讲解",
    "rag": "资料优先",
    "agent": "工具增强",
    "practice": "练习出题",
}

TEACHING_ACTION_LABELS = {
    "concept_check": "概念检查",
    "recall": "回忆检查",
    "review_recall": "复习回忆",
    "hint": "解题提示",
    "locate": "定位思路",
    "scaffold": "脚手架引导",
    "full_solution_after_two_stucks": "完整解法",
    "check_passed": "检查通过",
    "check_retry": "继续检查",
    "code_verified": "代码验证",
    "code_retry": "代码修正",
    "compare": "概念比较",
    "application_check": "应用检查",
    "smalltalk": "自然回应",
}

EXECUTION_MODE_LABELS = {
    "direct_answer": "直接回答",
    "tool_calling": "工具调用",
    "structured_output": "结构化回答",
    "deterministic_context": "确定性检索讲解",
}

TOOL_LABELS = {
    "notebook_retrieve": "搜索笔记本",
    "session_summary": "读取会话摘要",
    "learning_profile": "读取学习画像",
    "question_recommend": "推荐练习题",
    "web_search": "网络搜索",
    "web_extract": "网页读取",
    # 兼容旧历史消息，展示时统一收敛成 capability 风格名称。
    "search_notebook_context": "搜索笔记本",
    "get_session_summary": "读取会话摘要",
    "get_user_learning_profile": "读取学习画像",
    "recommend_questions": "推荐练习题",
    "mcp_web_search": "网络搜索",
    "mcp_web_read": "网页读取",
    "tavily_web_search": "网络搜索",
}


def build_user_message(question: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": question,
        "timestamp": int(time.time() * 1000) - 1,
    }


def build_assistant_message(final_state: dict[str, Any], *, include_process: bool | None = None) -> dict[str, Any]:
    explanation_payload = normalize_explanation_payload(final_state.get("explanation"))
    explanation = explanation_payload.model_dump()
    quiz_items = [normalize_quiz_item(item).model_dump() for item in (final_state.get("quiz_items") or [])]
    preserve_notebook_notice = should_preserve_notebook_notice(final_state)
    if explanation.get("steps") is not None:
        explanation["steps"] = clean_display_steps(
            explanation.get("steps"),
            preserve_notebook_notice=preserve_notebook_notice,
        )
    final_answer = compose_display_answer(
        str(final_state.get("final_answer", "") or ""),
        explanation,
        question_type=str(final_state.get("question_type") or ""),
        preserve_notebook_notice=preserve_notebook_notice,
    )
    if explanation.get("final_answer"):
        explanation["final_answer"] = clean_display_answer(
            str(explanation.get("final_answer") or ""),
            preserve_notebook_notice=preserve_notebook_notice,
        )
    topic = explanation_payload.topic.strip()
    if final_answer:
        content = final_answer
    elif topic:
        content = f"我已经围绕「{topic}」整理好讲解了。"
    elif quiz_items:
        content = "我已经帮你准备好一组练习题。"
    else:
        content = "这轮学习已经处理完成。"

    question_type = str(final_state.get("question_type", "") or "").strip()
    route = str(final_state.get("route", "") or "").strip()
    message = {
        "role": "assistant",
        "content": content,
        "timestamp": int(time.time() * 1000),
    }
    if question_type:
        message["questionType"] = question_type
    if route:
        message["route"] = route
    tool_invocation_trace = final_state.get("tool_invocation_trace") or final_state.get("toolInvocationTrace")
    if isinstance(tool_invocation_trace, dict):
        message["toolInvocationTrace"] = _safe_tool_invocation_trace(tool_invocation_trace)
    if explanation_payload.model_fields_set or any(explanation.values()):
        message["explanation"] = explanation
    if quiz_items:
        message["quiz"] = quiz_items
    if isinstance(final_state.get("quiz_request"), dict) and final_state.get("quiz_request"):
        message["quiz_request"] = final_state["quiz_request"]
    if isinstance(final_state.get("quiz_clarification"), dict) and final_state.get("quiz_clarification"):
        message["quiz_clarification"] = final_state["quiz_clarification"]
    if include_process is None:
        include_process = _include_process_in_history()
    if include_process:
        process = build_message_process(final_state)
        if process:
            message["process"] = process
    return message


def _include_process_in_history() -> bool:
    raw = os.getenv("CHAT_INCLUDE_PROCESS_IN_HISTORY", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _safe_tool_invocation_trace(raw: dict[str, Any]) -> dict[str, Any]:
    calls = raw.get("toolCalls") if isinstance(raw.get("toolCalls"), list) else []
    safe_calls: list[dict[str, Any]] = []
    for item in calls:
        if not isinstance(item, dict):
            continue
        payload: dict[str, Any] = {}
        for key in ("name", "type", "status", "startedAt", "endedAt"):
            value = item.get(key)
            if value is not None:
                payload[key] = str(value) if key in {"name", "type", "status", "startedAt", "endedAt"} else value
        if payload:
            safe_calls.append(payload)
    tool_call_count = int(raw.get("toolCallCount") or len(safe_calls) or 0)
    return {
        "currentDate": raw.get("currentDate"),
        "timezone": raw.get("timezone"),
        "knowledgeCutoff": raw.get("knowledgeCutoff"),
        "hasWebSearchTool": bool(raw.get("hasWebSearchTool")),
        "webSearchEnabled": bool(raw.get("webSearchEnabled")),
        "toolCallCount": tool_call_count,
        "toolCalls": safe_calls,
        "didAttemptWebSearch": bool(raw.get("didAttemptWebSearch") or _tool_trace_has_web_search_call(safe_calls)),
        "didUseWebSearch": bool(raw.get("didUseWebSearch")),
        "didUseAnyTool": bool(raw.get("didUseAnyTool") or tool_call_count > 0 or safe_calls),
    }


def _tool_trace_has_web_search_call(calls: list[dict[str, Any]]) -> bool:
    for call in calls:
        name = str(call.get("name") or call.get("capability") or "").strip().lower()
        source = str(call.get("type") or call.get("source") or "").strip().lower()
        if source == "web" or name == "web_search" or "web_search" in name:
            return True
    return False


def build_message_process(final_state: dict[str, Any]) -> dict[str, Any] | None:
    explanation = final_state.get("explanation") or {}
    reasoning_summary = str(final_state.get("reasoning_summary", "") or "").strip()
    if not reasoning_summary:
        reasoning_summary = str(explanation.get("thinking", "") or "").strip()

    stages = _build_process_stages(final_state)
    execution = _build_process_execution(final_state)
    tool_calls = _build_process_tool_calls(final_state)

    if not stages and not reasoning_summary and not execution and not tool_calls:
        return None

    current_stage = "已完成"
    if stages:
        current_stage = str(stages[-1].get("label", current_stage) or current_stage)

    process: dict[str, Any] = {
        "currentStage": current_stage,
        "stages": stages,
        "toolCalls": tool_calls,
    }
    if reasoning_summary:
        process["reasoningSummary"] = reasoning_summary
    if execution:
        process["execution"] = execution
    return process


def normalize_explanation_payload(raw: dict[str, Any] | None) -> ExplanationPayload:
    payload = dict(raw or {})
    for key in ("topic", "thinking", "mistakes", "final_answer"):
        if key in payload:
            payload[key] = strip_markdown_artifacts(str(payload.get(key) or ""))
    for key in ("steps", "similar"):
        if key in payload and isinstance(payload.get(key), list):
            payload[key] = strip_markdown_list([str(item) for item in payload.get(key) or []])
    mistakes = payload.get("mistakes", "")
    if isinstance(mistakes, list):
        payload["mistakes"] = "；".join(strip_markdown_list([str(item) for item in mistakes]))
    return ExplanationPayload.model_validate(payload)


def _stringify_tool_args(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value).strip()


def _summarize_tool_args(name: str, args: dict[str, Any]) -> str:
    if not isinstance(args, dict) or not args:
        return "无额外参数"

    parts: list[str] = []
    if name in {"notebook_retrieve", "search_notebook_context"}:
        query = _stringify_tool_args(args.get("query"))
        top_k = _stringify_tool_args(args.get("top_k"))
        if query:
            parts.append(f"query={query}")
        if top_k:
            parts.append(f"top_k={top_k}")
    elif name in {"session_summary", "get_session_summary"}:
        include_open_loops = _stringify_tool_args(args.get("include_open_loops"))
        if include_open_loops:
            parts.append(f"包含未解决点={include_open_loops}")
    elif name in {"learning_profile", "get_user_learning_profile"}:
        focus = _stringify_tool_args(args.get("focus"))
        if focus:
            parts.append(f"focus={focus}")
    elif name in {"question_recommend", "recommend_questions"}:
        topic = _stringify_tool_args(args.get("topic"))
        limit = _stringify_tool_args(args.get("limit"))
        if topic:
            parts.append(f"topic={topic}")
        if limit:
            parts.append(f"limit={limit}")
    elif name in {"web_search", "mcp_web_search", "tavily_web_search"}:
        query = _stringify_tool_args(args.get("query"))
        max_results = _stringify_tool_args(args.get("max_results"))
        if query:
            parts.append(f"query={query}")
        if max_results:
            parts.append(f"max_results={max_results}")
    elif name in {"web_extract", "mcp_web_read"}:
        url = _stringify_tool_args(args.get("url"))
        if url:
            parts.append(f"url={url}")
    else:
        for key, raw_value in list(args.items())[:3]:
            value = _stringify_tool_args(raw_value)
            if value:
                parts.append(f"{key}={value}")

    return " · ".join(parts) if parts else "无额外参数"


def _build_process_tool_calls(final_state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tool_calls = [
        *list(final_state.get("tool_calls") or []),
        *list(final_state.get("external_tool_calls") or []),
    ]
    normalized: list[dict[str, Any]] = []
    for item in raw_tool_calls:
        if not isinstance(item, dict):
            continue

        name = str(item.get("capability") or item.get("name", "") or "").strip()
        args = item.get("args", {})
        payload = {
            "name": name,
            "label": TOOL_LABELS.get(name, name or "未知工具"),
            "success": bool(item.get("success", False)),
            "argsSummary": _summarize_tool_args(name, args if isinstance(args, dict) else {}),
        }
        error = str(item.get("error", "") or "").strip()
        if error:
            payload["error"] = error
        if "doc_count" in item:
            payload["docCount"] = item.get("doc_count")
        normalized.append(payload)
    return normalized


def _build_process_execution(final_state: dict[str, Any]) -> dict[str, Any] | None:
    execution_mode = str(final_state.get("execution_mode", "") or "").strip()
    profile = final_state.get("selected_model_profile")
    profile_data = profile if isinstance(profile, dict) else {}
    runtime = final_state.get("graph_runtime")
    runtime_data = runtime if isinstance(runtime, dict) else {}
    model_attempts = list(final_state.get("model_attempts") or [])
    streaming_token_count = int(final_state.get("streaming_token_count") or 0)
    model_latency_ms = int(final_state.get("model_latency_ms") or runtime_data.get("latency_ms") or 0)
    streaming_mode = str(final_state.get("streaming_mode", "") or "").strip()
    streaming_degraded_reason = str(final_state.get("streaming_degraded_reason", "") or "").strip()

    if not execution_mode and not profile_data and "degraded" not in final_state:
        return None

    has_successful_attempt = any(
        isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "ok"
        for item in model_attempts
    )
    if bool(final_state.get("fallback_used", False)):
        call_status = "fallback"
    elif has_successful_attempt or streaming_token_count > 0:
        call_status = "ok"
    elif bool(final_state.get("degraded", False)):
        call_status = "failed"
    else:
        call_status = "unknown"

    execution: dict[str, Any] = {
        "mode": EXECUTION_MODE_LABELS.get(execution_mode, execution_mode or "未知模式"),
        "degraded": bool(final_state.get("degraded", False)),
        "modelId": str(profile_data.get("model_id", "") or "").strip(),
        "modelFamily": str(profile_data.get("family", "") or "").strip(),
        "primaryModelId": str(final_state.get("primary_model_id", "") or "").strip(),
        "fallbackModelId": str(final_state.get("fallback_model_id", "") or "").strip(),
        "fallbackUsed": bool(final_state.get("fallback_used", False)),
        "fallbackReason": str(final_state.get("fallback_reason", "") or "").strip(),
        "modelAttempts": model_attempts,
        "streamingMode": streaming_mode,
        "streamingTokenCount": streaming_token_count,
        "streamingDegradedReason": streaming_degraded_reason,
        "modelLatencyMs": model_latency_ms,
        "callStatus": call_status,
    }
    model_provider = str(profile_data.get("provider", "") or "").strip()
    if model_provider:
        execution["modelProvider"] = model_provider
    return execution


def _build_process_stages(final_state: dict[str, Any]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    question_type = str(final_state.get("question_type", "") or "").strip()
    if question_type:
        route = str(final_state.get("route", "") or "").strip()
        route_detail = f" · 路线：{ROUTE_LABELS.get(route, route)}" if route else ""
        notebook_policy = str(final_state.get("notebook_policy", "") or "").strip()
        search_policy = str(final_state.get("search_policy", "") or "").strip()
        policy_detail = ""
        if notebook_policy or search_policy:
            notebook_label = {
                "skip": "不查 notebook",
                "optional": "资料可选",
                "required": "优先参考资料",
                "strict": "只按资料",
            }.get(notebook_policy, notebook_policy)
            search_label = {
                "forbidden": "不搜索",
                "allowed": "可搜索",
                "required": "必须搜索",
            }.get(search_policy, search_policy)
            policy_detail = " · " + " · ".join(
                item for item in (notebook_label, search_label) if item
            )
        stages.append(
            {
                "key": "routing",
                "label": "问题识别",
                "status": "completed",
                "detail": f"已识别为{QUESTION_TYPE_LABELS.get(question_type, question_type)}{route_detail}{policy_detail}。",
            }
        )

    guard = final_state.get("guard") if isinstance(final_state.get("guard"), dict) else {}
    if guard:
        allow_tools = bool(guard.get("allow_tools", False))
        allow_search = bool(guard.get("allow_search", False))
        reason = str(guard.get("reason", "") or "").strip()
        stages.append(
            {
                "key": "guard",
                "label": "工具守卫",
                "status": "completed",
                "detail": (
                    f"工具：{'允许' if allow_tools else '禁用'} · "
                    f"搜索：{'允许' if allow_search else '禁用'}"
                    + (f" · {reason}" if reason else "")
                ),
            }
        )

    raw_tool_calls = [
        *list(final_state.get("tool_calls") or []),
        *list(final_state.get("external_tool_calls") or []),
    ]
    tool_decision_rounds = [
        item for item in list(final_state.get("tool_decision_rounds") or [])
        if isinstance(item, dict)
    ]
    if tool_decision_rounds:
        used_tools = [
            str(item.get("tool", "") or "")
            for item in tool_decision_rounds
            if str(item.get("tool", "") or "") not in {"", "none"}
        ]
        if used_tools:
            detail = f"模型完成 {len(tool_decision_rounds)} 轮工具判断，调用了 {len(used_tools)} 次工具。"
        else:
            detail = f"模型完成 {len(tool_decision_rounds)} 轮工具判断，决定直接回答。"
        stages.append(
            {
                "key": "tool_decision",
                "label": "工具决策",
                "status": "completed",
                "detail": detail,
            }
        )
    has_search_tool = any(
        isinstance(item, dict)
        and str(item.get("capability") or item.get("name") or "") in {"notebook_retrieve", "search_notebook_context"}
        for item in raw_tool_calls
    )
    retrieval_skipped_reason = str(final_state.get("retrieval_skipped_reason") or "").strip()
    if retrieval_skipped_reason and "retrieved_docs" not in final_state and not has_search_tool:
        detail = {
            "stable_concept_model_first": "判断为稳定概念，本轮未调用知识库或搜索。",
            "no_explicit_knowledge_base_signal": "没有检测到明确的知识库引用，本轮未调用知识库。",
            "external_search_quality_fallback_only": "联网搜索仅作为质量兜底，本轮先由模型回答。",
            "no_matching_knowledge_base": "没有匹配到需要检索的知识库。",
        }.get(retrieval_skipped_reason, "本轮未调用知识库检索。")
        stages.append(
            {
                "key": "retrieval_skipped",
                "label": "知识库策略",
                "status": "completed",
                "detail": detail,
            }
        )
    if "retrieved_docs" in final_state or has_search_tool:
        raw_retrieved_docs = list(final_state.get("raw_retrieved_docs") or [])
        retrieved_docs = list(final_state.get("retrieved_docs") or [])
        retrieval_diagnosis = (
            final_state.get("retrieval_diagnosis")
            if isinstance(final_state.get("retrieval_diagnosis"), dict)
            else {}
        )
        is_rewritten = bool(final_state.get("is_rewritten", False))
        doc_count = len(raw_retrieved_docs) if raw_retrieved_docs else len(retrieved_docs)
        detail = f"知识检索命中 {doc_count} 条内容。"
        if bool(final_state.get("web_search_used", False)):
            detail = f"当前 notebook 未命中足够内容，已使用网络搜索补充 {doc_count} 条上下文。"
        if doc_count == 0:
            detail = "知识检索未命中可用内容。"
        diagnosis = str(retrieval_diagnosis.get("diagnosis", "") or "")
        if diagnosis == "empty_knowledge_base":
            detail = "当前 notebook 暂无可检索资料。"
        elif diagnosis == "low_score":
            detail = f"{detail[:-1]}，但相关度偏低。"
        elif diagnosis == "no_matching_docs":
            detail = "当前 notebook 没有命中相关资料。"
        if is_rewritten:
            detail = f"{detail[:-1]}，并自动改写了查询。"
        stages.append(
            {
                "key": "retrieval",
                "label": "知识检索",
                "status": "completed",
                "detail": detail,
            }
        )

    context_audit = final_state.get("context_audit") if isinstance(final_state.get("context_audit"), dict) else {}
    if context_audit:
        raw_count = int(context_audit.get("raw_count") or len(final_state.get("raw_retrieved_docs") or []))
        verified_count = int(context_audit.get("verified_count") or len(final_state.get("verified_context") or []))
        discarded_count = int(context_audit.get("discarded_count") or max(0, raw_count - verified_count))
        reason = str(context_audit.get("reason", "") or "").strip()
        if verified_count:
            detail = f"上下文审查通过 {verified_count} 条，丢弃 {discarded_count} 条。"
        elif raw_count:
            detail = f"上下文审查未发现可用资料，已丢弃 {discarded_count or raw_count} 条。"
        else:
            detail = "上下文审查未发现可用资料。"
        if reason and not verified_count:
            detail = f"{detail[:-1]} · {reason}。"
        stages.append(
            {
                "key": "context_audit",
                "label": "上下文审查",
                "status": "completed",
                "detail": detail,
            }
        )

    teaching_action = str(final_state.get("last_teaching_action", "") or "").strip()
    if teaching_action:
        teaching_type = str(final_state.get("teaching_input_type", "") or "").strip()
        user_state = str(final_state.get("teaching_user_state", "") or "").strip()
        label = TEACHING_ACTION_LABELS.get(teaching_action, teaching_action)
        detail = f"{label}"
        if teaching_type:
            detail = f"{detail} · {teaching_type}"
        if user_state:
            detail = f"{detail} · {user_state}"
        if final_state.get("teaching_waiting_for_user"):
            detail = f"{detail} · 等待你的回答"
        stages.append(
            {
                "key": "teaching",
                "label": "教学策略",
                "status": "completed",
                "detail": detail,
            }
        )

    if bool(final_state.get("web_search_attempted", False)):
        retrieved_docs = list(final_state.get("retrieved_docs") or [])
        web_error = str(final_state.get("web_search_error", "") or "").strip()
        if bool(final_state.get("web_search_used", False)):
            detail = f"网络搜索成功，补充 {len(retrieved_docs)} 条上下文。"
        elif web_error:
            detail = f"网络搜索失败：{web_error}，已继续使用通用问答兜底。"
        else:
            detail = "已尝试网络搜索，但没有获得可用结果。"
        stages.append(
            {
                "key": "web_search",
                "label": "网络搜索",
                "status": "completed",
                "detail": detail,
            }
        )

    execution = _build_process_execution(final_state)
    if execution:
        execution_detail = execution["mode"]
        model_family = str(execution.get("modelFamily", "") or "").strip()
        model_id = str(execution.get("modelId", "") or "").strip()
        if model_family and model_id:
            execution_detail = f"{execution_detail} · {model_family} · {model_id}"
        elif model_id:
            execution_detail = f"{execution_detail} · {model_id}"
        if execution.get("degraded"):
            execution_detail = f"{execution_detail} · 已降级回退"
        if execution.get("fallbackUsed") and execution.get("primaryModelId") and execution.get("fallbackModelId"):
            execution_detail = (
                f"{execution_detail} · 已从 {execution['primaryModelId']} 回滚到 {execution['fallbackModelId']}"
            )
        streaming_count = int(execution.get("streamingTokenCount") or 0)
        latency_ms = int(execution.get("modelLatencyMs") or 0)
        if streaming_count > 0:
            execution_detail = f"{execution_detail} · 流式 {streaming_count} 段"
        if execution.get("streamingDegradedReason"):
            execution_detail = f"{execution_detail} · 流式降级"
        if latency_ms > 0:
            execution_detail = f"{execution_detail} · {latency_ms}ms"
        stages.append(
            {
                "key": "execution",
                "label": "模型执行",
                "status": "completed",
                "detail": execution_detail,
            }
        )

    final_answer = str(final_state.get("final_answer", "") or "").strip()
    explanation = final_state.get("explanation") or {}
    quiz_items = list(final_state.get("quiz_items") or [])
    quiz_status = final_state.get("quiz_generation_status") if isinstance(final_state.get("quiz_generation_status"), dict) else {}
    repair_attempt_count = int(quiz_status.get("repair_attempt_count") or 0) if quiz_status else 0
    if repair_attempt_count:
        repair_model_used = bool(quiz_status.get("repair_model_used", False))
        repair_replaced_count = int(quiz_status.get("repair_replaced_count") or 0)
        detail_parts = [
            f"质量门打回后已修复 {repair_attempt_count} 轮",
            f"替换/补齐 {repair_replaced_count} 道题" if repair_replaced_count else "",
            "已调用模型重新命题" if repair_model_used else "使用确定性备用题补齐",
        ]
        stages.append(
            {
                "key": "quality_repair",
                "label": "模型修题" if repair_model_used else "质量门复审",
                "status": "completed" if quiz_items else "failed",
                "detail": " · ".join(part for part in detail_parts if part),
            }
        )
    if final_answer or explanation or quiz_items:
        detail = "已生成最终回答。"
        current_stage = "已生成回答"
        if quiz_items:
            detail = f"已生成最终回答，并准备了 {len(quiz_items)} 道练习题。"
            fallback_count = int(quiz_status.get("fallback_count") or 0) if quiz_status else 0
            partial = bool(quiz_status.get("partial", False)) if quiz_status else False
            degraded_reason = str(quiz_status.get("degraded_reason", "") or "").strip() if quiz_status else ""
            if fallback_count:
                detail = f"{detail[:-1]}，其中 {fallback_count} 道使用备用题补齐。"
            if partial:
                detail = f"{detail[:-1]}，本轮只生成了部分题目。"
            if degraded_reason:
                detail = f"{detail} 降级原因：{degraded_reason}"
            current_stage = "练习题已准备"
        stages.append(
            {
                "key": "answer",
                "label": current_stage,
                "status": "completed",
                "detail": detail,
            }
        )

    return stages
