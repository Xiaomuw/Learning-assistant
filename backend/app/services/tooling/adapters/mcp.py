from __future__ import annotations

import time

from app.services.tooling.schemas import ToolExecutionRequest, ToolRegistration, ToolRiskLevel
from app.shared.schemas.agent_graphs import EvidenceChunk, ToolCapability, ToolResult, ToolStatus


class MCPWebSearchAdapter:
    """MCP provider for the generic ``web_search`` capability."""

    registration = ToolRegistration(
        tool_id="web_search:mcp",
        provider="mcp",
        capability=ToolCapability.WEB_SEARCH,
        description="MCP provider for web_search capability.",
        enabled=True,
        risk_level=ToolRiskLevel.MEDIUM,
    )

    def invoke(self, request: ToolExecutionRequest) -> ToolResult:
        started = time.perf_counter()
        try:
            agent_request = request.runtime_context.get("agent_request")
            if agent_request is None:
                from app.domains.qa.schemas import AgentRequest

                agent_request = AgentRequest(
                    user_id=str(request.user_id or request.input.get("user_id") or ""),
                    session_id=str(request.runtime_context.get("session_id") or ""),
                    subject_id=str(request.runtime_context.get("subject_id") or "general"),
                    subject_name=str(request.runtime_context.get("subject_name") or "通用知识"),
                    subject_description=str(request.runtime_context.get("subject_description") or ""),
                    question=str(request.input.get("query") or request.input_summary or ""),
                    question_type=str(request.runtime_context.get("question_type") or "qa"),
                    memory=dict(request.runtime_context.get("memory") or {}),
                    short_term_messages=list(request.runtime_context.get("short_term_messages") or []),
                    session_memory=dict(request.runtime_context.get("session_memory") or {}),
                    runtime_context={
                        **dict(request.runtime_context),
                        "allow_search": True,
                        "guard": {
                            **dict(request.runtime_context.get("guard") or {}),
                            "allow_search": True,
                        },
                    },
                )

            from app.services.tools.mcp_tools import mcp_search_available, mcp_web_search

            if not mcp_search_available(agent_request):
                raise RuntimeError("mcp_web_search_unavailable")

            payload = mcp_web_search(agent_request, request.input)
            evidence = [
                EvidenceChunk(
                    source_type="web",
                    source_id=str(doc.get("metadata", {}).get("url", "") or ""),
                    text=str(doc.get("content", "") or ""),
                    metadata={**dict(doc.get("metadata") or {}), "provider": "mcp"},
                    score=float(doc.get("score", 0.0) or 0.0),
                )
                for doc in list(payload.get("documents") or [])
                if isinstance(doc, dict)
            ]
            status = ToolStatus.SUCCESS
            error = ""
        except Exception as exc:
            payload = {}
            evidence = []
            status = ToolStatus.ERROR
            error = type(exc).__name__
        latency_ms = int((time.perf_counter() - started) * 1000)
        return ToolResult(
            tool_id=self.registration.tool_id,
            provider=self.registration.provider,
            capability=self.registration.capability,
            status=status,
            input_summary=request.input_summary,
            output=payload,
            evidence=evidence,
            latency_ms=latency_ms,
            error=error,
        )
