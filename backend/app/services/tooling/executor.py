from __future__ import annotations

from app.services.tooling.policy import ToolPolicyResolver
from app.services.tooling.registry import ToolRegistry
from app.services.tooling.schemas import ToolExecutionRequest, ToolRiskLevel
from app.shared.schemas.agent_graphs import ToolResult, ToolStatus


_RISK_RANK: dict[ToolRiskLevel, int] = {
    ToolRiskLevel.LOW: 0,
    ToolRiskLevel.MEDIUM: 1,
    ToolRiskLevel.HIGH: 2,
    ToolRiskLevel.WRITE: 3,
}


def _max_risk(left: ToolRiskLevel, right: ToolRiskLevel) -> ToolRiskLevel:
    return left if _RISK_RANK[left] >= _RISK_RANK[right] else right


class ToolExecutor:
    def __init__(self, *, registry: ToolRegistry, policy_resolver: ToolPolicyResolver) -> None:
        self.registry = registry
        self.policy_resolver = policy_resolver

    def execute(self, request: ToolExecutionRequest, *, provider: str | None = None) -> ToolResult:
        candidates = self.registry.find_by_capability(request.capability, provider=provider)
        if not candidates:
            return ToolResult(
                tool_id=f"{request.capability.value}:unavailable",
                provider=provider or "",
                capability=request.capability,
                status=ToolStatus.ERROR,
                input_summary=request.input_summary,
                error="tool_not_registered",
            )

        tool = candidates[0]
        decision = self.policy_resolver.resolve(
            source_policy=request.source_policy,
            capability=request.capability,
            risk_level=_max_risk(request.risk_level, tool.adapter.registration.risk_level),
            tenant_scope=tool.adapter.registration.tenant_scope,
            tenant_id=request.tenant_id,
            test_mode=request.test_mode,
        )
        if not decision.allowed:
            return ToolResult(
                tool_id=tool.tool_id,
                provider=tool.provider,
                capability=tool.capability,
                status=ToolStatus.BLOCKED,
                input_summary=request.input_summary,
                error=decision.reason,
            )

        return tool.adapter.invoke(request)
