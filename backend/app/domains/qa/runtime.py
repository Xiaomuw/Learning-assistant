"""
Q&A Runtime
===========
主问答链路的 create_agent / tool loop / structured output / fallback 封装。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from langchain_core.messages import HumanMessage
from loguru import logger

from app.infrastructure.llm.langsmith import trace_run
from app.infrastructure.llm.config import get_fallback_chat_model
from app.infrastructure.llm.profile import get_model_profile
from app.infrastructure.llm.provider import get_chat_llm
from app.domains.qa.answer_generation import (
    generate_plain_answer,
    generate_structured_answer,
    repair_structured_output,
)
from app.domains.qa.explanation_fallback import explain_for_qa_fallback
from app.domains.qa.middleware import postprocess_middleware, preprocess_middleware
from app.domains.qa.mode_selection import select_execution_mode
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

            if execution_mode == "tool_calling":
                try:
                    tool_payload = self._run_tool_loop(prepared_request)
                    result.raw_output = self._generate_structured_answer(
                        prepared_request,
                        tool_payload["conversation"],
                    )
                    result.retrieved_docs = tool_payload["retrieved_docs"]
                    result.is_rewritten = tool_payload["is_rewritten"]
                    result.contextual_query = tool_payload["contextual_query"]
                    result.retrieval_diagnosis = dict(tool_payload.get("retrieval_diagnosis") or {})
                    result.tool_calls = tool_payload["tool_calls"]
                    result.tool_decision_rounds = list(tool_payload.get("tool_decision_rounds") or [])
                    result.reasoning_summary = str(tool_payload.get("reasoning_summary", "") or "")
                    result.source_usage = str(tool_payload.get("source_usage") or "model")  # type: ignore[assignment]
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
                    result.raw_output = self._generate_structured_answer(
                        prepared_request,
                        [HumanMessage(content=prepared_request.question)],
                    )
                    result.contextual_query = prepared_request.question
                    result.reasoning_summary = "模型判断本轮可以直接回答，未调用工具。"
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
                result = self._run_deterministic_fallback(result)
            else:
                try:
                    result.raw_output = self._generate_plain_answer(prepared_request)
                    result.contextual_query = prepared_request.question
                    result.reasoning_summary = "模型判断本轮可以直接回复，未调用工具。"
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
            "short_term_context": self.request.short_term_context,
            "session_memory_context": self.request.session_memory_context,
            "long_term_context": self.request.long_term_context,
        }

    def _get_llm(self, *, temperature: float = 0.2):
        return get_chat_llm(
            default_model=self.model_profile.model_id,
            temperature=temperature,
            model_override=self.model_profile.model_id,
            timeout_seconds=18.0,
            max_retries=0,
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
    thinking = str(explanation.get("thinking") or "").strip()
    steps = [
        str(item).strip()
        for item in list(explanation.get("steps") or [])
        if str(item).strip()
    ]
    mistakes = str(explanation.get("mistakes") or "").strip()
    similar = [
        str(item).strip()
        for item in list(explanation.get("similar") or [])
        if str(item).strip()
    ]

    parts: list[str] = []
    if thinking:
        parts.append(thinking)
    if steps:
        parts.append("\n".join(f"{index}. {step}" for index, step in enumerate(steps[:5], 1)))
    if mistakes:
        parts.append(f"易错点：{mistakes}")
    if similar:
        parts.append(f"可以继续延伸：{'、'.join(similar[:3])}")
    answer = "\n\n".join(parts).strip()
    return answer[:1200]


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
