from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Protocol

from app.domains.qa.runtime import create_agent
from app.domains.qa.schemas import AgentRequest, AgentExecutionResult
from app.infrastructure.llm.provider import DEFAULT_CHAT_MODEL, get_model_profile
from app.orchestration.graphs.shared.schemas import (
    ConceptRef,
    EvidenceChunk,
    FinalResponse,
    GraphError,
    GraphErrorSeverity,
    GraphType,
    LearningEvent,
    LearningEventType,
    SourceLevel,
    SourcePolicy,
    ToolCapability,
    ToolResult,
    ToolStatus,
    build_learning_event,
)
from app.shared.schemas.subject import DEFAULT_SUBJECTS, DEFAULT_SUBJECT_ID


class QARuntimeAdapter(Protocol):
    """Adapter seam for legacy or deterministic QA runtimes."""

    def answer(
        self,
        *,
        question: str,
        question_type: str,
        source_policy: str,
        evidence: list[EvidenceChunk],
        evidence_gate: dict[str, Any],
        user_id: str = "",
        graph_run_id: str = "",
    ) -> FinalResponse:
        """Return a contract-level final response without mutating graph state."""


@dataclass(frozen=True)
class QARuntimeContractResult:
    """Contract-safe result produced by read-only QA runtime adapters."""

    final_response: FinalResponse
    evidence: list[EvidenceChunk] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    learning_events: list[LearningEvent] = field(default_factory=list)
    errors: list[GraphError] = field(default_factory=list)
    runtime_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeterministicQARuntimeAdapter:
    """Small test-safe QA adapter used until the legacy runtime is wrapped."""

    def answer(
        self,
        *,
        question: str,
        question_type: str,
        source_policy: str,
        evidence: list[EvidenceChunk],
        evidence_gate: dict[str, Any],
        user_id: str = "",
        graph_run_id: str = "",
    ) -> FinalResponse:
        _ = (user_id, graph_run_id)
        if evidence_gate.get("insufficient"):
            missing_topic = str(evidence_gate.get("missing_topic") or question or "当前问题")
            return FinalResponse(
                answer=(
                    "当前 notebook 资料不足，无法只依据 notebook 回答这个问题。"
                    f"请补充与「{missing_topic}」相关的资料，或切换到允许外部资料的 source_policy。"
                ),
                source_level=SourceLevel.NONE,
                coach_actions=["request_more_notebook_evidence"],
                ui_payload={
                    "target_graph_type": GraphType.QA.value,
                    "answer_mode": "insufficient_notebook",
                    "source_policy": source_policy,
                    "evidence_sufficiency": evidence_gate,
                },
            )

        concepts = _concepts_from_question(question=question, question_type=question_type)
        source_level = _source_level_from_evidence(evidence)
        evidence_refs = [item.id for item in evidence]
        if evidence:
            lead = evidence[0].text.strip().replace("\n", " ")
            answer = f"根据已审核资料，{lead}"
            if not answer.endswith(("。", ".", "！", "!", "？", "?")):
                answer = f"{answer}。"
        else:
            answer = f"{question.strip()}：这是一个可以先用通用知识解释的问题。"

        return FinalResponse(
            answer=answer,
            source_level=source_level,
            concepts=concepts,
            evidence_refs=evidence_refs,
            coach_actions=["explain_concept" if question_type == "concept" else "answer_question"],
            mastery_signals={"signal_strength": "weak", "source_policy": source_policy},
            ui_payload={
                "target_graph_type": GraphType.QA.value,
                "answer_mode": "grounded_qa" if evidence else "model_only",
                "source_policy": source_policy,
                "evidence_sufficiency": evidence_gate,
            },
        )


@dataclass(frozen=True)
class ProductionQARuntimeAdapter:
    """Production adapter around ``domains.qa.runtime`` through graph contracts."""

    model_name: str = DEFAULT_CHAT_MODEL
    user_id: str = ""
    session_id: str = ""
    subject_id: str = DEFAULT_SUBJECT_ID
    subject_name: str = str(DEFAULT_SUBJECTS[0]["name"])
    subject_description: str = ""
    memory: dict[str, Any] = field(default_factory=dict)
    short_term_messages: list[dict[str, Any]] = field(default_factory=list)
    short_term_context: str = ""
    session_memory: dict[str, Any] = field(default_factory=dict)
    session_memory_context: str = ""
    long_term_context: str = ""
    runtime_context: dict[str, Any] = field(default_factory=dict)
    allow_tools: bool = False
    allow_search: bool = False

    def answer(
        self,
        *,
        question: str,
        question_type: str,
        source_policy: str,
        evidence: list[EvidenceChunk],
        evidence_gate: dict[str, Any],
        user_id: str = "",
        graph_run_id: str = "",
    ) -> FinalResponse:
        return self.answer_with_contract(
            question=question,
            question_type=question_type,
            source_policy=source_policy,
            evidence=evidence,
            evidence_gate=evidence_gate,
            user_id=user_id,
            graph_run_id=graph_run_id,
        ).final_response

    def answer_with_contract(
        self,
        *,
        question: str,
        question_type: str,
        source_policy: str,
        evidence: list[EvidenceChunk],
        evidence_gate: dict[str, Any],
        user_id: str = "",
        graph_run_id: str = "",
    ) -> QARuntimeContractResult:
        runtime_user_id = user_id or self.user_id
        runtime_graph_run_id = graph_run_id or str(self.runtime_context.get("graph_run_id") or "")
        runtime_context = self._build_runtime_context(
            question=question,
            source_policy=source_policy,
            evidence=evidence,
            evidence_gate=evidence_gate,
        )
        message_id = str(runtime_context.get("message_id") or runtime_context.get("request_id") or "").strip()
        request = AgentRequest(
            user_id=runtime_user_id,
            session_id=self.session_id,
            subject_id=self.subject_id,
            subject_name=self.subject_name,
            subject_description=self.subject_description,
            question=question,
            question_type=question_type,
            memory=dict(self.memory),
            short_term_messages=list(self.short_term_messages),
            short_term_context=self.short_term_context,
            session_memory=dict(self.session_memory),
            session_memory_context=self.session_memory_context,
            long_term_context=self.long_term_context,
            model_name=self.model_name,
            runtime_context=runtime_context,
        )
        model_profile = get_model_profile(self.model_name)
        try:
            result = create_agent(
                request,
                _runtime_state(request, evidence, evidence_gate),
                model_profile,
            ).run()
        except Exception as exc:
            return _contract_result_from_exception(
                exc=exc,
                question=question,
                question_type=question_type,
                source_policy=source_policy,
                evidence=evidence,
                evidence_gate=evidence_gate,
                user_id=runtime_user_id,
                graph_run_id=runtime_graph_run_id,
                session_id=self.session_id,
                message_id=message_id,
            )
        return _contract_result_from_runtime_result(
            result=result,
            question=question,
            question_type=question_type,
            source_policy=source_policy,
            input_evidence=evidence,
            evidence_gate=evidence_gate,
            user_id=runtime_user_id,
            graph_run_id=runtime_graph_run_id,
            session_id=self.session_id,
            message_id=message_id,
        )

    def _build_runtime_context(
        self,
        *,
        question: str,
        source_policy: str,
        evidence: list[EvidenceChunk],
        evidence_gate: dict[str, Any],
    ) -> dict[str, Any]:
        docs = [_evidence_to_runtime_doc(item) for item in evidence]
        notebook_required = bool(evidence_gate.get("notebook_required")) or source_policy == SourcePolicy.NOTEBOOK_ONLY.value
        notebook_policy = "strict" if source_policy == SourcePolicy.NOTEBOOK_ONLY.value else ("required" if notebook_required else "optional")
        runtime_source_policy = _runtime_source_policy(source_policy=source_policy, evidence=evidence)
        runtime_allow_tools = False
        runtime_allow_search = False
        base_context = {
            "rag_precomputed": True,
            "rag_ready": bool(evidence),
            "retrieved_docs": docs,
            "verified_context": docs,
            "raw_retrieved_docs": [],
            "context_audit": {
                "usable": bool(evidence),
                "verified_count": len(evidence),
                "decision": "keep" if evidence else "discard",
                **dict(evidence_gate or {}),
            },
            "notebook_retrieved": any(item.source_type in {"notebook", "course"} for item in evidence),
            "notebook_context": "\n\n".join(item.text for item in evidence),
            "contextual_query": question,
            "contract_source_policy": source_policy,
            "source_policy": runtime_source_policy,
            "notebook_policy": notebook_policy,
            "notebook_required": notebook_required,
            "allow_tools": runtime_allow_tools,
            "allow_search": runtime_allow_search,
            "qagraph_runtime_tools_disabled": True,
            "qagraph_requested_allow_tools": self.allow_tools,
            "qagraph_requested_allow_search": self.allow_search,
            "guard": {
                "allow_tools": runtime_allow_tools,
                "allow_search": runtime_allow_search,
                "reason": "qagraph_runtime_adapter_uses_precomputed_evidence_only",
            },
        }
        base_context.update(dict(self.runtime_context))
        base_context["allow_tools"] = runtime_allow_tools
        base_context["allow_search"] = runtime_allow_search
        base_context["guard"] = {
            **dict(base_context.get("guard") or {}),
            "allow_tools": runtime_allow_tools,
            "allow_search": runtime_allow_search,
            "reason": "qagraph_runtime_adapter_uses_precomputed_evidence_only",
        }
        return base_context


def _concepts_from_question(*, question: str, question_type: str) -> list[ConceptRef]:
    if question_type != "concept":
        return []
    topic = question.strip().strip("？?。.!！")
    for prefix in ("什么是", "什么叫", "解释一下", "解释", "define", "what is"):
        if topic.lower().startswith(prefix):
            topic = topic[len(prefix) :].strip(" ：:，,")
            break
    return [ConceptRef(concept_id=topic.lower()[:64], name=topic or "当前概念", confidence=0.7, source="qa_adapter")]


def _source_level_from_evidence(evidence: list[EvidenceChunk]) -> SourceLevel:
    if not evidence:
        return SourceLevel.MODEL
    source_types = {item.source_type for item in evidence}
    if source_types <= {"notebook", "course"}:
        return SourceLevel.NOTEBOOK
    if source_types <= {"web"}:
        return SourceLevel.WEB
    return SourceLevel.MIXED


def _evidence_to_runtime_doc(evidence: EvidenceChunk) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "content": evidence.text,
        "document": evidence.text,
        "source_type": evidence.source_type,
        "source_id": evidence.source_id,
        "score": evidence.score,
        "metadata": dict(evidence.metadata),
    }


def _runtime_state(
    request: AgentRequest,
    evidence: list[EvidenceChunk],
    evidence_gate: dict[str, Any],
) -> dict[str, Any]:
    docs = [_evidence_to_runtime_doc(item) for item in evidence]
    return {
        "user_id": request.user_id,
        "session_id": request.session_id,
        "subject_id": request.subject_id,
        "subject_name": request.subject_name,
        "subject_description": request.subject_description,
        "question": request.question,
        "question_type": request.question_type,
        "model_name": request.model_name,
        "thinking_mode": bool(request.runtime_context.get("thinking_mode", False)),
        "memory": dict(request.memory),
        "short_term_messages": list(request.short_term_messages),
        "short_term_context": request.short_term_context,
        "session_memory": dict(request.session_memory),
        "session_memory_context": request.session_memory_context,
        "long_term_context": request.long_term_context,
        "rag_precomputed": True,
        "rag_ready": bool(evidence),
        "retrieved_docs": docs,
        "verified_context": docs,
        "notebook_context": "\n\n".join(item.text for item in evidence),
        "context_audit": dict(evidence_gate),
        "notebook_required": request.runtime_context.get("notebook_required", False),
        "notebook_policy": request.runtime_context.get("notebook_policy", "optional"),
        "source_policy": request.runtime_context.get("source_policy", "open_tools"),
    }


def _contract_result_from_runtime_result(
    *,
    result: AgentExecutionResult,
    question: str,
    question_type: str,
    source_policy: str,
    input_evidence: list[EvidenceChunk],
    evidence_gate: dict[str, Any],
    user_id: str,
    graph_run_id: str,
    session_id: str = "",
    message_id: str = "",
) -> QARuntimeContractResult:
    runtime_evidence = _evidence_from_runtime_docs(result.retrieved_docs)
    evidence = _merge_evidence(input_evidence, runtime_evidence)
    tool_results = _tool_results_from_runtime(result=result, evidence=evidence)
    errors = _errors_from_runtime_result(result=result, answer_text=_answer_text(result))
    learning_events = _adapter_learning_events(
        result=result,
        tool_results=tool_results,
        user_id=user_id,
        graph_run_id=graph_run_id,
        source_policy=source_policy,
        question=question,
        session_id=session_id,
        message_id=message_id,
    )
    final_response = _final_response_from_runtime_result(
        result=result,
        question=question,
        question_type=question_type,
        source_policy=source_policy,
        evidence=evidence,
        evidence_gate=evidence_gate,
    )
    runtime_summary = {
        "execution_mode": result.execution_mode,
        "degraded": result.degraded,
        "tool_calls_count": len(result.tool_calls),
        "tool_decision_rounds_count": len(result.tool_decision_rounds),
        "tool_decision_rounds": list(result.tool_decision_rounds),
        "retrieved_docs_count": len(result.retrieved_docs),
        "retrieval_diagnosis": dict(result.retrieval_diagnosis),
        "reasoning_summary": result.reasoning_summary,
        "source_usage": result.source_usage,
        "model_unavailable_reason": result.model_unavailable_reason,
        "primary_model_id": result.primary_model_id,
        "fallback_model_id": result.fallback_model_id,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "model_attempts": list(result.model_attempts),
        "streaming_mode": result.streaming_mode,
        "streaming_token_count": result.streaming_token_count,
        "streaming_degraded_reason": result.streaming_degraded_reason,
        "learner_context_summary_present": bool(result.learner_context_summary),
    }
    return QARuntimeContractResult(
        final_response=final_response,
        evidence=evidence,
        tool_results=tool_results,
        learning_events=learning_events,
        errors=errors,
        runtime_summary=runtime_summary,
    )


def _final_response_from_runtime_result(
    *,
    result: AgentExecutionResult,
    question: str,
    question_type: str,
    source_policy: str,
    evidence: list[EvidenceChunk],
    evidence_gate: dict[str, Any],
) -> FinalResponse:
    answer_text = _answer_text(result)
    explanation_payload = (
        result.answer.model_dump(exclude={"final_answer"})
        if result.answer is not None
        else {}
    )

    concepts = _concepts_from_question(question=question, question_type=question_type)
    if result.answer is not None and result.answer.topic:
        topic = result.answer.topic.strip()
        concepts = [
            ConceptRef(
                concept_id=topic.lower()[:64],
                name=topic,
                confidence=0.75,
                source="production_qa_runtime",
            )
        ]

    evidence_refs = [item.id for item in evidence]
    source_level = _source_level_from_runtime_source(result.source_usage, evidence)
    return FinalResponse(
        answer=answer_text,
        source_level=source_level,
        concepts=concepts,
        evidence_refs=evidence_refs,
        coach_actions=["explain_concept" if question_type == "concept" else "answer_question"],
        mastery_signals={"signal_strength": "weak", "source_policy": source_policy},
        ui_payload={
            "target_graph_type": GraphType.QA.value,
            "answer_mode": "production_qa_runtime",
            "source_policy": source_policy,
            "evidence_sufficiency": evidence_gate,
            "execution_mode": result.execution_mode,
            "degraded": result.degraded,
            "tool_calls_count": len(result.tool_calls),
            "tool_decision_rounds_count": len(result.tool_decision_rounds),
            "retrieved_docs_count": len(result.retrieved_docs),
            "reasoning_summary": result.reasoning_summary,
            "explanation": explanation_payload,
            "learner_context_summary_present": bool(result.learner_context_summary),
            "selected_model_profile": result.selected_model_profile,
            "primary_model_id": result.primary_model_id,
            "fallback_model_id": result.fallback_model_id,
            "fallback_used": result.fallback_used,
            "fallback_reason": result.fallback_reason,
            "model_attempts": list(result.model_attempts),
            "streaming_mode": result.streaming_mode,
            "streaming_token_count": result.streaming_token_count,
            "streaming_degraded_reason": result.streaming_degraded_reason,
        },
    )


def _source_level_from_runtime_source(source_usage: str, evidence: list[EvidenceChunk]) -> SourceLevel:
    normalized = str(source_usage or "").strip()
    try:
        return SourceLevel(normalized)
    except ValueError:
        return _source_level_from_evidence(evidence)


def _answer_text(result: AgentExecutionResult) -> str:
    answer_text = str(result.final_answer or "").strip()
    if not answer_text and result.answer is not None:
        answer_text = str(result.answer.final_answer or result.answer.thinking or "").strip()
    if not answer_text:
        answer_text = str(result.raw_output or "").strip()
    return answer_text or "这一轮没有生成可用回答。"


def _contract_result_from_exception(
    *,
    exc: Exception,
    question: str,
    question_type: str,
    source_policy: str,
    evidence: list[EvidenceChunk],
    evidence_gate: dict[str, Any],
    user_id: str,
    graph_run_id: str,
    session_id: str = "",
    message_id: str = "",
) -> QARuntimeContractResult:
    _ = evidence_gate
    final_response = FinalResponse(
        answer="这一轮问答链路暂时不可用，我先安全停止，避免给出不可靠回答。",
        source_level=_source_level_from_evidence(evidence) if evidence else SourceLevel.NONE,
        concepts=_concepts_from_question(question=question, question_type=question_type),
        evidence_refs=[item.id for item in evidence],
        coach_actions=["retry_qa_runtime"],
        mastery_signals={"signal_strength": "none", "source_policy": source_policy},
        ui_payload={
            "target_graph_type": GraphType.QA.value,
            "answer_mode": "production_qa_runtime_error",
            "source_policy": source_policy,
            "error_type": exc.__class__.__name__,
        },
    )
    error = GraphError(
        code="production_qa_runtime_error",
        message=exc.__class__.__name__,
        node="ProductionQARuntimeAdapter",
        severity=GraphErrorSeverity.ERROR,
        metadata={"source_policy": source_policy},
    )
    event = build_learning_event(
        event_type=LearningEventType.ANSWER_REPAIRED.value,
        user_id=user_id,
        graph_run_id=graph_run_id,
        payload={
            "reason": "production_qa_runtime_error",
            "error_type": exc.__class__.__name__,
        },
        source_object_type="qa_runtime_error",
        source_object_id=_qa_runtime_source_id(
            question=question,
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
        ),
    )
    return QARuntimeContractResult(
        final_response=final_response,
        evidence=evidence,
        errors=[error],
        learning_events=[event],
        runtime_summary={"error_type": exc.__class__.__name__},
    )


def _evidence_from_runtime_docs(docs: list[dict[str, Any]]) -> list[EvidenceChunk]:
    evidence: list[EvidenceChunk] = []
    for index, raw_doc in enumerate(docs, 1):
        if not isinstance(raw_doc, dict):
            continue
        text = str(
            raw_doc.get("content")
            or raw_doc.get("document")
            or raw_doc.get("text")
            or ""
        ).strip()
        if not text:
            continue
        metadata = raw_doc.get("metadata") if isinstance(raw_doc.get("metadata"), dict) else {}
        source_type = _source_type_from_runtime_doc(raw_doc, metadata)
        source_id = str(
            raw_doc.get("source_id")
            or raw_doc.get("doc_id")
            or raw_doc.get("id")
            or metadata.get("source_id")
            or metadata.get("url")
            or metadata.get("file_name")
            or ""
        )
        evidence_id = str(raw_doc.get("id") or raw_doc.get("doc_id") or f"runtime-doc-{index}")
        evidence.append(
            EvidenceChunk(
                id=evidence_id,
                source_type=source_type,
                source_id=source_id,
                text=text,
                metadata=dict(metadata),
                score=_clamped_score(raw_doc.get("score")),
            )
        )
    return evidence


def _source_type_from_runtime_doc(raw_doc: dict[str, Any], metadata: dict[str, Any]) -> str:
    explicit = str(raw_doc.get("source_type") or metadata.get("source_type") or "").strip()
    if explicit:
        return explicit
    retrieval_source = str(metadata.get("retrieval_source") or "").lower()
    if "tavily" in retrieval_source or retrieval_source.startswith("mcp_web") or "web" in retrieval_source:
        return "web"
    if metadata.get("url") and not metadata.get("subject_id"):
        return "web"
    return "notebook"


def _clamped_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _merge_evidence(
    first: list[EvidenceChunk],
    second: list[EvidenceChunk],
) -> list[EvidenceChunk]:
    merged: dict[str, EvidenceChunk] = {}
    for item in [*first, *second]:
        merged[item.id] = item
    return list(merged.values())


def _tool_results_from_runtime(
    *,
    result: AgentExecutionResult,
    evidence: list[EvidenceChunk],
) -> list[ToolResult]:
    tool_results: list[ToolResult] = []
    for index, raw_call in enumerate(result.tool_calls, 1):
        if not isinstance(raw_call, dict):
            continue
        name = str(raw_call.get("name") or raw_call.get("capability") or f"runtime_tool_{index}")
        capability = _capability_from_tool_call(raw_call)
        success = bool(raw_call.get("success", False))
        error = str(raw_call.get("error") or "").strip()
        status = ToolStatus.SUCCESS if success else _tool_status_from_error(error)
        public_source = _public_source_for_tool(capability)
        tool_results.append(
            ToolResult(
                tool_id=f"runtime:{capability.value}:{index}",
                provider=public_source,
                capability=capability,
                status=status,
                input_summary=_input_summary_from_tool_call(raw_call),
                output={
                    "tool_capability": capability.value,
                    "source": public_source,
                    "doc_count": int(raw_call.get("doc_count") or 0),
                    "is_external": bool(raw_call.get("is_external", False)),
                    "payload_keys": sorted(
                        str(key) for key in raw_call.keys()
                        if str(key) not in {"args", "raw_output", "document", "content"}
                    ),
                },
                evidence=_evidence_for_capability(evidence, capability),
                latency_ms=int(raw_call.get("latency_ms") or 0),
                error=error,
            )
        )
    return tool_results


def _capability_from_tool_call(raw_call: dict[str, Any]) -> ToolCapability:
    explicit = str(raw_call.get("capability") or "").strip()
    if explicit:
        try:
            return ToolCapability(explicit)
        except ValueError:
            pass
    name = str(raw_call.get("name") or "")
    normalized = name.lower()
    if "notebook" in normalized:
        return ToolCapability.NOTEBOOK_RETRIEVE
    if "web_read" in normalized or "extract" in normalized:
        return ToolCapability.WEB_EXTRACT
    if "web" in normalized or "tavily" in normalized or "search" in normalized:
        return ToolCapability.WEB_SEARCH
    return ToolCapability.NOTEBOOK_RETRIEVE


def _public_source_for_tool(capability: ToolCapability) -> str:
    if capability in {ToolCapability.WEB_SEARCH, ToolCapability.WEB_EXTRACT}:
        return "web"
    if capability == ToolCapability.NOTEBOOK_RETRIEVE:
        return "notebook"
    return "runtime"


def _tool_status_from_error(error: str) -> ToolStatus:
    normalized = error.lower()
    if "timeout" in normalized or "timed out" in normalized or "超时" in normalized:
        return ToolStatus.TIMEOUT
    return ToolStatus.ERROR


def _input_summary_from_tool_call(raw_call: dict[str, Any]) -> str:
    capability = _capability_from_tool_call(raw_call)
    source = _public_source_for_tool(capability)
    doc_count = int(raw_call.get("doc_count") or 0)
    if doc_count:
        return f"{capability.value} · source={source} · docs={doc_count}"
    return f"{capability.value} · source={source}"


def _evidence_for_capability(
    evidence: list[EvidenceChunk],
    capability: ToolCapability,
) -> list[EvidenceChunk]:
    if capability == ToolCapability.NOTEBOOK_RETRIEVE:
        return [item for item in evidence if item.source_type in {"notebook", "course"}]
    if capability in {ToolCapability.WEB_SEARCH, ToolCapability.WEB_EXTRACT}:
        return [item for item in evidence if item.source_type == "web"]
    return []


def _errors_from_runtime_result(
    *,
    result: AgentExecutionResult,
    answer_text: str,
) -> list[GraphError]:
    errors: list[GraphError] = []
    if result.degraded:
        errors.append(
            GraphError(
                code="qa_runtime_degraded",
                message="Production QA runtime used fallback or degraded mode.",
                node="ProductionQARuntimeAdapter",
                severity=GraphErrorSeverity.WARNING,
                metadata={"execution_mode": result.execution_mode},
            )
        )
    if result.model_unavailable_reason:
        errors.append(
            GraphError(
                code="model_unavailable",
                message="Selected chat model is unavailable for the current runtime.",
                node="ProductionQARuntimeAdapter",
                severity=GraphErrorSeverity.WARNING,
                metadata={
                    "reason": result.model_unavailable_reason,
                    "execution_mode": result.execution_mode,
                },
            )
        )
    if not answer_text or answer_text == "这一轮没有生成可用回答。":
        errors.append(
            GraphError(
                code="empty_answer",
                message="Production QA runtime returned an empty answer.",
                node="ProductionQARuntimeAdapter",
                severity=GraphErrorSeverity.WARNING,
                metadata={"execution_mode": result.execution_mode},
            )
        )
    for raw_call in result.tool_calls:
        if not isinstance(raw_call, dict) or bool(raw_call.get("success", False)):
            continue
        capability = _capability_from_tool_call(raw_call)
        error = str(raw_call.get("error") or "tool_call_failed")
        errors.append(
            GraphError(
                code="tool_timeout" if _tool_status_from_error(error) == ToolStatus.TIMEOUT else "tool_call_failed",
                message=error[:240],
                node="ProductionQARuntimeAdapter",
                severity=GraphErrorSeverity.WARNING,
                metadata={"tool_capability": capability.value, "source": _public_source_for_tool(capability)},
            )
        )
    return errors


def _adapter_learning_events(
    *,
    result: AgentExecutionResult,
    tool_results: list[ToolResult],
    user_id: str,
    graph_run_id: str,
    source_policy: str,
    question: str,
    session_id: str = "",
    message_id: str = "",
) -> list[LearningEvent]:
    events: list[LearningEvent] = []
    source_id = _qa_runtime_source_id(
        question=question,
        user_id=user_id,
        session_id=session_id,
        message_id=message_id,
    )
    if tool_results:
        tool_refs = [item.tool_id for item in tool_results]
        events.append(
            build_learning_event(
                event_type=LearningEventType.TOOL_FALLBACK_USED.value,
                user_id=user_id,
                graph_run_id=graph_run_id,
                payload={
                    "tool_result_refs": tool_refs,
                    "tool_statuses": [item.status.value for item in tool_results],
                    "source_policy": source_policy,
                },
                source_object_type="tool_results",
                source_object_id=f"{source_id}:tools:{_short_hash('|'.join(tool_refs))}",
            )
        )
    if result.degraded:
        events.append(
            build_learning_event(
                event_type=LearningEventType.ANSWER_REPAIRED.value,
                user_id=user_id,
                graph_run_id=graph_run_id,
                payload={
                    "reason": "production_qa_runtime_degraded",
                    "execution_mode": result.execution_mode,
                    "source_policy": source_policy,
                },
                source_object_type="qa_runtime",
                source_object_id=f"{source_id}:degraded:{result.execution_mode}",
            )
        )
    return events


def _qa_runtime_source_id(*, question: str, user_id: str, session_id: str = "", message_id: str = "") -> str:
    explicit = str(message_id or "").strip()
    if explicit:
        return f"qa_message:{explicit}"
    scope = str(session_id or user_id or "unknown").strip()
    digest = hashlib.sha256(str(question or "").strip().encode("utf-8")).hexdigest()[:16]
    return f"qa_message:{scope}:{digest}"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _runtime_source_policy(*, source_policy: str, evidence: list[EvidenceChunk]) -> str:
    if source_policy == SourcePolicy.NOTEBOOK_ONLY.value:
        return "notebook"
    if source_policy == SourcePolicy.NOTEBOOK_PLUS_EXTERNAL.value:
        evidence_types = {item.source_type for item in evidence}
        if "web" in evidence_types and evidence_types & {"notebook", "course"}:
            return "mixed"
        if "web" in evidence_types:
            return "web"
        return "notebook" if evidence else "none"
    return "none"
