"""
Q&A Runtime
===========
主问答链路的 create_agent / tool loop / structured output / fallback 封装。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from loguru import logger

from app.infrastructure.llm.langsmith import trace_run
from app.infrastructure.llm.config import get_fallback_chat_model
from app.infrastructure.llm.profile import get_model_profile
from app.infrastructure.llm.provider import get_chat_llm
from app.shared.markdown_cleaning import compact_answer_summary, strip_markdown_artifacts
from app.domains.qa.answer_generation import (
    generate_plain_answer,
    generate_structured_answer,
    repair_structured_output,
)
from app.domains.qa.explanation_fallback import explain_for_qa_fallback
from app.domains.qa.middleware import postprocess_middleware, preprocess_middleware
from app.domains.qa.mode_selection import select_execution_mode
from app.domains.qa.prompts import build_tool_system_message, message_to_text
from app.domains.qa.retrieval_fallback import retrieve_for_qa_fallback
from app.domains.qa.schemas import (
    AgentExecutionResult,
    AgentRequest,
    AnswerSchema,
)
from app.domains.qa.tool_loop import run_tool_loop
from app.domains.qa.tracing import build_qa_trace_outputs
from app.shared.schemas.model_profile import ModelProfile


@dataclass
class QARuntimeAgent:
    request: AgentRequest
    state: dict[str, Any]
    model_profile: ModelProfile

    def run(self) -> AgentExecutionResult:
        with trace_run(
            name="qa_agent.runtime",
            run_type="chain",
            inputs=self._build_runtime_trace_inputs(),
            metadata={"model_id": self.model_profile.model_id},
            tags=["qa-runtime", f"model:{self.model_profile.family.lower()}"],
        ) as runtime_run:
            prepared_request = preprocess_middleware(self.request, self.model_profile)
            execution_mode = select_execution_mode(prepared_request, self.model_profile)
            logger.info(
                f"🤖 QA runtime 启动 | mode={execution_mode} | model={self.model_profile.model_id}"
            )

            result = AgentExecutionResult(
                execution_mode=execution_mode,
                selected_model_profile=self.model_profile.to_dict(),
                primary_model_id=self.model_profile.model_id,
            )
            runtime_run.metadata["execution_mode"] = execution_mode
            runtime_run.metadata["thinking_mode"] = bool(
                prepared_request.runtime_context.get("thinking_mode", False)
            )
            stream_answer_tokens = _should_stream_answer_tokens(prepared_request)
            if stream_answer_tokens:
                self._emit_stream_status(
                    stream_stage="model_start",
                    stage_label="模型执行",
                    detail="模型已开始生成回答，回答内容会实时显示。",
                    safe_decision_summary=_safe_execution_summary(execution_mode, prepared_request),
                )

            if execution_mode == "tool_calling":
                try:
                    self._emit_stream_status(
                        stream_stage="tool_decision",
                        stage_label="工具决策",
                        detail="正在判断是否需要调用 notebook、搜索或学习上下文工具。",
                        safe_decision_summary="只展示工具选择摘要，不展示原始隐藏思维链。",
                    )
                    tool_payload = self._run_tool_loop(prepared_request)
                    result.retrieved_docs = tool_payload["retrieved_docs"]
                    result.is_rewritten = tool_payload["is_rewritten"]
                    result.contextual_query = tool_payload["contextual_query"]
                    result.retrieval_diagnosis = dict(tool_payload.get("retrieval_diagnosis") or {})
                    result.tool_calls = tool_payload["tool_calls"]
                    result.tool_decision_rounds = list(tool_payload.get("tool_decision_rounds") or [])
                    result.reasoning_summary = str(tool_payload.get("reasoning_summary", "") or "")
                    result.source_usage = str(tool_payload.get("source_usage") or "model")  # type: ignore[assignment]
                    self._emit_stream_status(
                        stream_stage="tool_result",
                        stage_label="工具决策",
                        detail=(
                            f"工具决策完成：{len(result.tool_decision_rounds)} 轮判断，"
                            f"{len(result.tool_calls)} 次工具调用。"
                        ),
                        safe_decision_summary=result.reasoning_summary,
                        status="completed",
                    )
                    if stream_answer_tokens:
                        result.raw_output = self._generate_streamed_plain_answer(
                            prepared_request,
                            conversation=list(tool_payload["conversation"]),
                        )
                        result.answer = _streamed_answer_schema(str(result.raw_output or ""), prepared_request)
                        result.final_answer = result.answer.final_answer
                    else:
                        result.raw_output = self._generate_structured_answer(
                            prepared_request,
                            tool_payload["conversation"],
                        )
                except Exception as exc:
                    fallback_result = self._try_fallback_model(
                        prepared_request,
                        execution_mode=execution_mode,
                        initial_error=exc,
                    )
                    if fallback_result is not None:
                        result = fallback_result
                    else:
                        logger.warning(f"⚠️ Tool calling 失败，回退到确定性主链路: {exc}")
                        result.degraded = True
                        result.model_unavailable_reason = _model_unavailable_reason(exc)
                        result = self._run_deterministic_fallback(result)

            elif execution_mode == "structured_output":
                try:
                    if stream_answer_tokens:
                        result.raw_output = self._generate_streamed_plain_answer(
                            prepared_request,
                            conversation=[HumanMessage(content=prepared_request.question)],
                        )
                        result.answer = _streamed_answer_schema(str(result.raw_output or ""), prepared_request)
                        result.final_answer = result.answer.final_answer
                    else:
                        result.raw_output = self._generate_structured_answer(
                            prepared_request,
                            [HumanMessage(content=prepared_request.question)],
                        )
                    result.contextual_query = prepared_request.question
                    result.reasoning_summary = (
                        "模型判断本轮可以直接回答，未调用工具；回答内容已安全实时输出。"
                        if stream_answer_tokens
                        else "模型判断本轮可以直接回答，未调用工具。"
                    )
                    result.source_usage = "model"
                except Exception as exc:
                    fallback_result = self._try_fallback_model(
                        prepared_request,
                        execution_mode=execution_mode,
                        initial_error=exc,
                    )
                    if fallback_result is not None:
                        result = fallback_result
                    else:
                        logger.warning(f"⚠️ structured output 失败，回退到确定性主链路: {exc}")
                        result.degraded = True
                        result.model_unavailable_reason = _model_unavailable_reason(exc)
                        result = self._run_deterministic_fallback(result)
            elif execution_mode == "deterministic_context":
                result.degraded = True
                if stream_answer_tokens and not _strict_notebook_context_missing(prepared_request):
                    try:
                        result.raw_output = self._generate_streamed_plain_answer(prepared_request)
                        result.answer = _streamed_answer_schema(str(result.raw_output or ""), prepared_request)
                        result.final_answer = result.answer.final_answer
                        result.contextual_query = prepared_request.question
                        result.reasoning_summary = (
                            "当前模型/端点不支持稳定结构化输出，本轮改用安全 plaintext 实时回答。"
                        )
                        result.source_usage = _streaming_source_usage(prepared_request)  # type: ignore[assignment]
                    except Exception as exc:
                        logger.warning(f"⚠️ deterministic_context 流式回答失败，回退到确定性主链路: {exc}")
                        result.model_unavailable_reason = _model_unavailable_reason(exc)
                        result.streaming_degraded_reason = exc.__class__.__name__
                        result = self._run_deterministic_fallback(result)
                else:
                    result = self._run_deterministic_fallback(result)
            else:
                try:
                    if stream_answer_tokens:
                        result.raw_output = self._generate_streamed_plain_answer(prepared_request)
                        result.answer = _streamed_answer_schema(str(result.raw_output or ""), prepared_request)
                        result.final_answer = result.answer.final_answer
                    else:
                        result.raw_output = self._generate_plain_answer(prepared_request)
                    result.contextual_query = prepared_request.question
                    result.reasoning_summary = (
                        "模型判断本轮可以直接回复，未调用工具；回答内容已安全实时输出。"
                        if stream_answer_tokens
                        else "模型判断本轮可以直接回复，未调用工具。"
                    )
                    result.source_usage = "model"
                except Exception as exc:
                    fallback_result = self._try_fallback_model(
                        prepared_request,
                        execution_mode=execution_mode,
                        initial_error=exc,
                    )
                    if fallback_result is not None:
                        result = fallback_result
                    else:
                        logger.warning(f"⚠️ direct answer 失败，回退到确定性主链路: {exc}")
                        result.degraded = True
                        result.model_unavailable_reason = _model_unavailable_reason(exc)
                        result = self._run_deterministic_fallback(result)

            result.streaming_token_count = int(prepared_request.runtime_context.get("streaming_token_count") or 0)
            result.streaming_mode = str(
                prepared_request.runtime_context.get("streaming_mode")
                or result.streaming_mode
                or "node"
            )
            result.streaming_degraded_reason = str(
                prepared_request.runtime_context.get("streaming_degraded_reason")
                or result.streaming_degraded_reason
                or ""
            )
            if stream_answer_tokens and not _should_stream_answer_tokens(prepared_request):
                result.streaming_mode = "node"
                result.streaming_degraded_reason = (
                    result.streaming_degraded_reason or "provider_stream_returned_no_chunks"
                )
            if result.streaming_token_count <= 0 and result.streaming_mode == "token":
                result.streaming_mode = "node"
                result.streaming_degraded_reason = (
                    result.streaming_degraded_reason or "provider_stream_returned_no_chunks"
                )

            processed = postprocess_middleware(
                result,
                self.model_profile,
                question_type=prepared_request.question_type,
                repair=lambda raw: self._repair_structured_output(prepared_request, raw),
                fallback=lambda: self._run_deterministic_fallback(result),
            )
            _ensure_model_attempts(processed, current_model=self.model_profile.model_id)
            runtime_run.metadata.update(
                {
                    "degraded": processed.degraded,
                    "tool_calls_count": len(processed.tool_calls),
                    "fallback_used": processed.fallback_used,
                    "primary_model_id": processed.primary_model_id,
                    "fallback_model_id": processed.fallback_model_id,
                    "streaming_mode": processed.streaming_mode,
                    "streaming_token_count": processed.streaming_token_count,
                    "streaming_degraded_reason": processed.streaming_degraded_reason,
                }
            )
            runtime_run.end(outputs=build_qa_trace_outputs(processed))
            return processed

    def _build_runtime_trace_inputs(self) -> dict[str, Any]:
        return {
            "question": self.request.question,
            "question_type": self.request.question_type,
            "subject_id": self.request.subject_id,
            "session_id": self.request.session_id,
            "model_name": self.request.model_name,
            "thinking_mode": bool(self.request.runtime_context.get("thinking_mode", False)),
            "route": str(self.request.runtime_context.get("route") or ""),
            "source_policy": str(self.request.runtime_context.get("source_policy") or ""),
            "notebook_policy": str(self.request.runtime_context.get("notebook_policy") or ""),
            "search_policy": str(self.request.runtime_context.get("search_policy") or ""),
            "retrieval_diagnosis": dict(self.request.runtime_context.get("retrieval_diagnosis") or {}),
            "short_term_context": self.request.short_term_context,
            "session_memory_context": self.request.session_memory_context,
            "long_term_context": self.request.long_term_context,
        }

    def _get_llm(self, *, temperature: float = 0.2):
        return get_chat_llm(
            default_model=self.model_profile.model_id,
            temperature=temperature,
            model_override=self.model_profile.model_id,
            timeout_seconds=None,
            max_retries=0,
            thinking_mode=bool(self.request.runtime_context.get("thinking_mode", False)),
        )

    def _try_fallback_model(
        self,
        request: AgentRequest,
        *,
        execution_mode: str,
        initial_error: Exception,
    ) -> AgentExecutionResult | None:
        fallback_model = get_fallback_chat_model()
        current_model = self.model_profile.model_id
        if not fallback_model or fallback_model == current_model:
            return None
        if not _should_try_fallback_model(initial_error):
            return None

        logger.warning(
            f"⚠️ 主模型 {current_model} 调用失败，尝试备用模型 {fallback_model}: {initial_error}"
        )
        fallback_profile = get_model_profile(fallback_model)
        fallback_request = replace(request, model_name=fallback_model)
        fallback_state = dict(self.state)
        fallback_state["primary_model_error"] = _model_unavailable_reason(initial_error) or "primary_model_failed"
        fallback_state["model_name"] = fallback_model
        fallback_result = QARuntimeAgent(
            request=fallback_request,
            state=fallback_state,
            model_profile=fallback_profile,
        ).run()
        fallback_result.degraded = True
        fallback_reason = _model_unavailable_reason(initial_error) or "primary_model_failed"
        fallback_result.primary_model_id = current_model
        fallback_result.fallback_model_id = fallback_model
        fallback_result.fallback_used = True
        fallback_result.fallback_reason = fallback_reason
        fallback_result.model_unavailable_reason = fallback_reason
        fallback_result.model_attempts = [
            {
                "model_id": current_model,
                "role": "primary",
                "status": "failed",
                "reason": fallback_reason,
            },
            {
                "model_id": fallback_model,
                "role": "fallback",
                "status": "ok",
            },
        ]
        fallback_result.reasoning_summary = (
            fallback_result.reasoning_summary
            or "主模型暂时不可用，本轮已使用备用模型完成回答。"
        )
        fallback_result.selected_model_profile = fallback_profile.to_dict()
        return fallback_result

    def _run_tool_loop(self, request: AgentRequest) -> dict[str, Any]:
        return run_tool_loop(request=request, get_llm=self._get_llm)

    def _generate_structured_answer(
        self,
        request: AgentRequest,
        conversation: list[Any],
    ) -> AnswerSchema | str | dict[str, Any]:
        return generate_structured_answer(
            request=request,
            conversation=conversation,
            model_profile=self.model_profile,
            get_llm=self._get_llm,
        )

    def _generate_plain_answer(self, request: AgentRequest) -> str:
        return generate_plain_answer(request=request, get_llm=self._get_llm)

    def _generate_streamed_plain_answer(
        self,
        request: AgentRequest,
        conversation: list[Any] | None = None,
    ) -> str:
        llm = self._get_llm(temperature=0.3)
        messages = _streaming_answer_messages(request, conversation=conversation)
        chunks: list[str] = []
        token_count = 0
        reasoning_char_count = 0
        reasoning_stream_seen = False
        thinking_mode_enabled = bool(request.runtime_context.get("thinking_mode", False))
        self._emit_stream_status(
            stream_stage="answer_stream",
            stage_label="正在生成回答",
            detail="正在接收模型的实时回答片段。",
            safe_decision_summary=(
                "回答正文会实时展示；思考模式下原始思考只在本轮调试面板临时显示。"
                if thinking_mode_enabled
                else "回答正文会实时展示；内部工具选择和质量判断只显示安全摘要。"
            ),
        )
        try:
            for chunk in llm.stream(messages):
                reasoning_delta = _stream_reasoning_delta_to_text(chunk) if thinking_mode_enabled else ""
                if reasoning_delta:
                    if not reasoning_stream_seen:
                        reasoning_stream_seen = True
                        request.runtime_context["reasoning_stream_seen"] = True
                        self._emit_stream_status(
                            stream_stage="reasoning_stream",
                            stage_label="模型思考",
                            detail="正在接收模型思考过程。",
                            safe_decision_summary="调试信息仅本轮展示，不进入回答正文、历史或 LangSmith。",
                        )
                    reasoning_char_count += len(reasoning_delta)
                    request.runtime_context["reasoning_trace_char_count"] = reasoning_char_count
                    self._emit_stream_event(
                        "reasoning_delta",
                        {
                            "delta": reasoning_delta,
                            "streaming_mode": "token",
                            "source": "deepseek_reasoning_content",
                            "ephemeral": True,
                        },
                    )

                delta = _stream_delta_to_text(chunk)
                if not delta:
                    continue
                chunks.append(delta)
                token_count += 1
                self._emit_stream_event(
                    "answer_delta",
                    {
                        "delta": delta,
                        "streaming_mode": "token",
                        "is_synthetic_delta": False,
                    },
                )
        except Exception as exc:
            request.runtime_context["stream_answer_tokens"] = False
            request.runtime_context["streaming_degraded_reason"] = exc.__class__.__name__
            logger.warning(f"⚠️ 模型 token 流式失败，回退到非流式回答: {exc.__class__.__name__}")
            response = llm.invoke(messages)
            request.runtime_context["streaming_token_count"] = token_count
            return message_to_text(response).strip()

        text = "".join(chunks).strip()
        if not text:
            response = llm.invoke(messages)
            text = message_to_text(response).strip()
            if text:
                request.runtime_context["stream_answer_tokens"] = False
                request.runtime_context["streaming_degraded_reason"] = (
                    request.runtime_context.get("streaming_degraded_reason")
                    or "provider_stream_returned_no_chunks"
                )
        request.runtime_context["streaming_token_count"] = token_count
        if reasoning_char_count > 0:
            request.runtime_context["reasoning_trace_char_count"] = reasoning_char_count
        if token_count > 0:
            request.runtime_context["streaming_mode"] = "token"
        if reasoning_stream_seen:
            self._emit_stream_status(
                stream_stage="reasoning_stream",
                stage_label="模型思考",
                detail=f"模型思考流接收完成，共 {reasoning_char_count} 个字符。",
                safe_decision_summary="原始思考过程仅用于本轮调试观察，未写入历史或 LangSmith。",
                status="completed",
            )
        self._emit_stream_status(
            stream_stage="answer_stream",
            stage_label="正在生成回答",
            detail=f"实时回答生成完成，共接收 {token_count} 个片段。",
            safe_decision_summary="已完成安全实时输出，最终答案会由结束事件校准。",
            status="completed",
        )
        return text

    def _emit_stream_status(
        self,
        *,
        stream_stage: str,
        stage_label: str,
        detail: str,
        safe_decision_summary: str = "",
        status: str = "running",
    ) -> None:
        payload = {
            "stream_stage": stream_stage,
            "stage_label": stage_label,
            "detail": detail,
            "safe_decision_summary": safe_decision_summary,
            "status": status,
        }
        streaming_mode = str((self.request.runtime_context or {}).get("streaming_mode") or "").strip()
        if streaming_mode:
            payload["streaming_mode"] = streaming_mode
        reasoning_trace_char_count = int(
            (self.request.runtime_context or {}).get("reasoning_trace_char_count") or 0
        )
        if reasoning_trace_char_count > 0:
            payload["reasoning_trace_char_count"] = reasoning_trace_char_count
        self._emit_stream_event(
            "status",
            payload,
        )

    def _emit_stream_event(self, event: str, data: dict[str, Any]) -> None:
        if not _should_stream_answer_tokens(self.request):
            return
        runtime_writer = (self.request.runtime_context or {}).get("stream_writer")
        if callable(runtime_writer):
            try:
                runtime_writer({"event": event, "data": data})
            except Exception as exc:  # noqa: BLE001 - streaming telemetry must never break QA
                logger.debug(f"QA injected stream event skipped: {exc.__class__.__name__}")
            return
        try:
            writer = get_stream_writer()
        except Exception:
            return
        try:
            writer({"event": event, "data": data})
        except Exception as exc:  # noqa: BLE001 - streaming telemetry must never break QA
            logger.debug(f"QA custom stream event skipped: {exc.__class__.__name__}")

    def _repair_structured_output(
        self,
        request: AgentRequest,
        raw_output: Any,
    ) -> AnswerSchema | None:
        _ = request
        return repair_structured_output(
            raw_output=raw_output,
            model_profile=self.model_profile,
            get_llm=self._get_llm,
        )

    def _run_deterministic_fallback(
        self,
        result: AgentExecutionResult,
    ) -> AgentExecutionResult:
        if result.model_unavailable_reason and not result.model_attempts:
            result.primary_model_id = result.primary_model_id or self.model_profile.model_id
            result.model_attempts = [
                {
                    "model_id": result.primary_model_id,
                    "role": "primary",
                    "status": "failed",
                    "reason": result.model_unavailable_reason,
                }
            ]
        with trace_run(
            name="qa_agent.fallback",
            run_type="chain",
            inputs={
                "question": self.request.question,
                "question_type": self.request.question_type,
                "reason": "runtime_degraded",
            },
            metadata={"subject_id": self.request.subject_id},
            tags=["qa-runtime", "fallback"],
        ) as fallback_run:
            fallback_state = dict(self.state)
            if self.request.runtime_context.get("rag_precomputed"):
                verified_context = list(
                    self.request.runtime_context.get("verified_context")
                    or self.request.runtime_context.get("retrieved_docs")
                    or []
                )
                retrieval_update = {
                    "raw_retrieved_docs": list(self.request.runtime_context.get("raw_retrieved_docs") or []),
                    "verified_context": verified_context,
                    "retrieved_docs": verified_context,
                    "notebook_retrieved": bool(self.request.runtime_context.get("notebook_retrieved", False)),
                    "notebook_context": str(self.request.runtime_context.get("notebook_context", "") or ""),
                    "context_audit": dict(self.request.runtime_context.get("context_audit") or {}),
                    "is_rewritten": bool(self.request.runtime_context.get("is_rewritten", False)),
                    "contextual_query": str(
                        self.request.runtime_context.get("contextual_query")
                        or self.request.question
                    ),
                    "retrieval_diagnosis": dict(
                        self.request.runtime_context.get("retrieval_diagnosis") or {}
                    ),
                }
            else:
                retrieval_update = retrieve_for_qa_fallback(fallback_state)
            fallback_state.update(retrieval_update)
            notebook_policy = str(
                fallback_state.get("notebook_policy")
                or self.request.runtime_context.get("notebook_policy")
                or "skip"
            )
            notebook_required = bool(
                fallback_state.get("notebook_required")
                or self.request.runtime_context.get("notebook_required")
                or notebook_policy == "strict"
            )
            fallback_state["notebook_required"] = notebook_required
            fallback_state["fallback_safe_no_context"] = notebook_required
            explanation_update = explain_for_qa_fallback(fallback_state)
            fallback_state.update(explanation_update)
            if fallback_state.get("model_unavailable_reason"):
                result.model_unavailable_reason = str(fallback_state.get("model_unavailable_reason") or "")
            learner_context_summary = str(fallback_state.get("learner_context_summary") or "")

            final_answer = _compose_teaching_final_answer(
                fallback_state.get("explanation", {}) if isinstance(fallback_state.get("explanation"), dict) else {}
            )
            answer = AnswerSchema(
                topic=str(fallback_state.get("explanation", {}).get("topic", "当前问题") or "当前问题"),
                thinking=str(
                    fallback_state.get("explanation", {}).get("thinking", "我已经结合当前资料整理出一版讲解。")
                ),
                steps=list(fallback_state.get("explanation", {}).get("steps", []) or []),
                mistakes=str(fallback_state.get("explanation", {}).get("mistakes", "") or ""),
                similar=list(fallback_state.get("explanation", {}).get("similar", []) or []),
                final_answer=final_answer or str(
                    fallback_state.get("explanation", {}).get("thinking", "我已经整理好当前问题的讲解。")
                ),
            )
            result.answer = answer
            result.final_answer = answer.final_answer
            result.learner_context_summary = learner_context_summary
            result.retrieved_docs = list(fallback_state.get("retrieved_docs", []) or [])
            result.is_rewritten = bool(fallback_state.get("is_rewritten", False))
            result.contextual_query = str(
                fallback_state.get("contextual_query", self.request.question) or self.request.question
            )
            result.retrieval_diagnosis = dict(fallback_state.get("retrieval_diagnosis") or {})
            result.reasoning_summary = str(
                fallback_state.get("reasoning_summary")
                or fallback_state.get("explanation", {}).get("thinking", "")
                or ""
            )
            result.source_usage = str(fallback_state.get("source_usage") or "model")  # type: ignore[assignment]
            fallback_run.end(outputs=build_qa_trace_outputs(result))
            return result


def create_agent(
    request: AgentRequest,
    state: dict[str, Any],
    model_profile: ModelProfile,
) -> QARuntimeAgent:
    return QARuntimeAgent(request=request, state=state, model_profile=model_profile)


def _compose_teaching_final_answer(explanation: dict[str, Any]) -> str:
    explicit_final = str(explanation.get("final_answer") or "").strip()
    if explicit_final:
        return compact_answer_summary(explicit_final)

    thinking = strip_markdown_artifacts(str(explanation.get("thinking") or "").strip())
    steps = [
        strip_markdown_artifacts(str(item).strip())
        for item in list(explanation.get("steps") or [])
        if str(item).strip()
    ]
    if thinking:
        return compact_answer_summary(thinking)
    if steps:
        return compact_answer_summary(steps[0])
    return "我已经整理好这轮讲解，下面按结构给你拆开看。"


def _model_unavailable_reason(exc: Exception) -> str:
    message = str(exc).lower()
    if "401" in message or "unauthorized" in message or "subscription tier" in message or "not available" in message:
        return "unauthorized_model"
    return ""


def _should_try_fallback_model(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_markers = (
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "subscription tier",
        "not available",
        "model",
        "rate limit",
        "timeout",
        "connection",
        "api",
    )
    return any(marker in message for marker in retryable_markers)


def _should_stream_answer_tokens(request: AgentRequest) -> bool:
    return bool((request.runtime_context or {}).get("stream_answer_tokens"))


def _strict_notebook_context_missing(request: AgentRequest) -> bool:
    runtime_context = request.runtime_context or {}
    source_policy = getattr(request, "source_policy", "") or runtime_context.get("source_policy") or ""
    if str(source_policy or "").strip().lower() != "notebook_only":
        return False
    if any(
        str(value or "").strip()
        for value in (
            request.short_term_context,
            request.session_memory_context,
            request.long_term_context,
        )
    ):
        return False
    retrieved_docs = runtime_context.get("retrieved_docs") or runtime_context.get("documents") or []
    return not bool(retrieved_docs)


def _streaming_source_usage(request: AgentRequest) -> str:
    runtime_context = request.runtime_context or {}
    retrieved_docs = runtime_context.get("retrieved_docs") or runtime_context.get("documents") or []
    if retrieved_docs:
        return "mixed"
    source_policy = getattr(request, "source_policy", "") or runtime_context.get("source_policy") or ""
    if str(source_policy or "").strip().lower() == "notebook_only":
        return "mixed"
    return "model"


def _safe_execution_summary(execution_mode: str, request: AgentRequest) -> str:
    thinking_note = (
        "思考模式已启用：模型会进行更充分推理，但界面只展示安全摘要和最终回答。"
        if bool((request.runtime_context or {}).get("thinking_mode", False))
        else ""
    )
    if execution_mode == "tool_calling":
        summary = "本轮会先判断是否需要工具，再生成最终回答。"
    elif execution_mode == "structured_output":
        summary = "本轮判断为可直接回答，会以安全实时流式展示回答正文。"
    elif execution_mode == "direct_answer":
        summary = "本轮是轻量直接回复，会以安全实时流式展示回答正文。"
    else:
        summary = "本轮会先整理上下文，再生成回答。"
    return f"{thinking_note}{summary}" if thinking_note else summary


def _streaming_answer_messages(
    request: AgentRequest,
    *,
    conversation: list[Any] | None = None,
) -> list[Any]:
    stream_instruction = (
        "\n\n## 实时回答要求\n"
        "- 直接面向学习者输出自然语言答案，不要输出 JSON。\n"
        "- 不要暴露原始思维链、系统提示、工具调试信息、检索分数或内部异常。\n"
        "- 可以简要说明使用了资料/搜索/通用知识，但只给可审计的结论摘要。\n"
        "- 面向手机小屏输出：用短自然段和简短编号组织，不要把多个知识点挤在一段里。\n"
        "- 不要使用 Markdown 表格、分隔线、粗体、引用或代码块；不要输出 ||、---、### 这类排版符号。\n"
        "- 用 2 到 5 个短自然段组织回答；需要列点时最多 4 点，每点一句话。\n"
    )
    if conversation:
        return [
            SystemMessage(content=f"{build_tool_system_message(request)}{stream_instruction}"),
            *conversation,
            HumanMessage(content="请基于以上上下文直接给出最终学习回答，不要输出 JSON。"),
        ]
    return [
        SystemMessage(content=f"{build_tool_system_message(request)}{stream_instruction}"),
        HumanMessage(content=request.question),
    ]


def _streamed_answer_schema(text: str, request: AgentRequest) -> AnswerSchema:
    answer = _truncate_stream_text(
        strip_markdown_artifacts(text or "这一轮没有生成可用回答。"),
        1200,
    )
    topic = _topic_from_streamed_answer(request)
    steps = _streamed_answer_steps(answer)
    final_answer = compact_answer_summary(answer, max_chars=140)
    thinking = _streamed_answer_intro(request)
    return AnswerSchema(
        topic=topic,
        thinking=thinking,
        steps=steps or [final_answer or answer],
        mistakes="",
        similar=["继续追问这个主题", "让我结合你的笔记本继续解释"],
        final_answer=final_answer or thinking or answer,
    )


def _streamed_answer_intro(request: AgentRequest) -> str:
    question_type = str(request.question_type or "").strip()
    if question_type in {"compare", "comparison"}:
        return "我会先分别定位两个概念，再把差异放到同一组维度里对照。"
    if question_type in {"problem", "practice", "mcq_problem"}:
        return "我会先抓题干中的关键条件，再把判断步骤拆成可复盘的小段。"
    if question_type in {"review", "recap"}:
        return "我会先提炼最该记住的核心点，再补上容易混淆的地方。"
    if question_type in {"smalltalk", "meta"}:
        return "我会先直接回应你的问题，再给出下一步可以继续聊的方向。"
    return "我会先用核心概念定位这个问题，再拆成几个容易吸收的要点。"


def _streamed_answer_steps(answer: str) -> list[str]:
    cleaned = strip_markdown_artifacts(answer)
    if not cleaned:
        return ["这一轮没有生成可用回答。"]

    raw_parts = [part.strip() for part in re.split(r"\n{1,}|\s*[；;]\s*", cleaned) if part.strip()]
    if len(raw_parts) <= 1:
        raw_parts = [
            part.strip()
            for part in re.split(r"(?<=[。！？!?])\s*", cleaned)
            if part.strip()
        ]
    if len(raw_parts) <= 1:
        raw_parts = _split_long_streamed_text(cleaned)

    steps: list[str] = []
    for part in raw_parts:
        compact = " ".join(strip_markdown_artifacts(part).split())
        if not compact:
            continue
        if len(compact) > 260:
            steps.extend(_split_long_streamed_text(compact, max_chars=180))
        else:
            steps.append(compact)
        if len(steps) >= 5:
            break
    return steps[:5] or [compact_answer_summary(cleaned, max_chars=180)]


def _split_long_streamed_text(text: str, *, max_chars: int = 180) -> list[str]:
    normalized = " ".join(strip_markdown_artifacts(text).split())
    if len(normalized) <= max_chars:
        return [normalized] if normalized else []
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？!?])", normalized)
        if sentence.strip()
    ]
    if len(sentences) <= 1:
        return [normalized[index : index + max_chars].strip() for index in range(0, len(normalized), max_chars)]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current}{sentence}" if current else sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _topic_from_streamed_answer(request: AgentRequest) -> str:
    topic = request.question.strip().strip("？?。.!！")
    for prefix in ("什么是", "什么叫", "解释一下", "解释", "define", "what is"):
        if topic.lower().startswith(prefix):
            topic = topic[len(prefix) :].strip(" ：:，,")
            break
    return _truncate_stream_text(topic or "当前问题", 120)


def _truncate_stream_text(text: str, max_length: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1] + "…"


def _stream_delta_to_text(chunk: Any) -> str:
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = str(item.get("type") or "").lower()
                if item_type in {"reasoning", "thinking", "reasoning_content"}:
                    continue
                text = item.get("text") or item.get("content") or ""
            else:
                text = str(item)
            if text:
                parts.append(str(text))
        return "".join(parts)
    if isinstance(content, dict):
        item_type = str(content.get("type") or "").lower()
        if item_type in {"reasoning", "thinking", "reasoning_content"}:
            return ""
        text = content.get("text") or content.get("content") or ""
        return str(text)
    return str(content)


def _stream_reasoning_delta_to_text(chunk: Any) -> str:
    parts: list[str] = []
    for attr_name in ("additional_kwargs", "response_metadata"):
        metadata = getattr(chunk, attr_name, None)
        if isinstance(metadata, dict):
            value = metadata.get("reasoning_content")
            if value:
                parts.append(str(value))

    content = getattr(chunk, "content", chunk)
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").lower()
            if item_type not in {"reasoning", "thinking", "reasoning_content"}:
                continue
            text = item.get("reasoning_content") or item.get("text") or item.get("content") or ""
            if text:
                parts.append(str(text))
    elif isinstance(content, dict):
        item_type = str(content.get("type") or "").lower()
        if item_type in {"reasoning", "thinking", "reasoning_content"}:
            text = content.get("reasoning_content") or content.get("text") or content.get("content") or ""
            if text:
                parts.append(str(text))

    return "".join(parts)


def _ensure_model_attempts(result: AgentExecutionResult, *, current_model: str) -> None:
    if result.model_attempts:
        return
    if result.execution_mode == "deterministic_context":
        return
    model_id = result.selected_model_profile.get("model_id") if isinstance(result.selected_model_profile, dict) else ""
    model_id = str(model_id or current_model or result.primary_model_id or "").strip()
    if not model_id:
        return
    result.primary_model_id = result.primary_model_id or model_id
    result.model_attempts = [
        {
            "model_id": model_id,
            "role": "primary",
            "status": "ok" if not result.fallback_used else "failed",
        }
    ]
