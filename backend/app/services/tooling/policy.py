from __future__ import annotations

from app.services.tooling.schemas import ToolPolicyDecision, ToolRiskLevel
from app.shared.schemas.agent_graphs import SourcePolicy, ToolCapability


_SOURCE_POLICY_CAPABILITIES: dict[SourcePolicy, frozenset[ToolCapability]] = {
    SourcePolicy.NOTEBOOK_ONLY: frozenset({ToolCapability.NOTEBOOK_RETRIEVE}),
    SourcePolicy.NOTEBOOK_PLUS_EXTERNAL: frozenset(
        {
            ToolCapability.NOTEBOOK_RETRIEVE,
            ToolCapability.WEB_SEARCH,
            ToolCapability.WEB_EXTRACT,
        }
    ),
    SourcePolicy.OPEN_TOOLS: frozenset(ToolCapability),
}


class ToolPolicyResolver:
    """Decides whether a graph may use a capability before provider execution."""

    def __init__(self, *, allow_write_tools: bool = False) -> None:
        self.allow_write_tools = allow_write_tools

    def resolve(
        self,
        *,
        source_policy: SourcePolicy | str,
        capability: ToolCapability,
        risk_level: ToolRiskLevel = ToolRiskLevel.LOW,
        tenant_scope: str | None = None,
        tenant_id: str | None = None,
        test_mode: bool = False,
    ) -> ToolPolicyDecision:
        policy = SourcePolicy(str(source_policy or SourcePolicy.OPEN_TOOLS.value))

        if tenant_scope and tenant_id and tenant_scope != tenant_id:
            return ToolPolicyDecision(allowed=False, reason="tenant_scope_mismatch")

        if test_mode and risk_level in {ToolRiskLevel.WRITE, ToolRiskLevel.HIGH}:
            return ToolPolicyDecision(allowed=False, reason="test_mode_blocks_high_risk_tool")

        if risk_level == ToolRiskLevel.WRITE and not self.allow_write_tools:
            return ToolPolicyDecision(allowed=False, reason="write_tools_disabled")

        allowed_capabilities = _SOURCE_POLICY_CAPABILITIES[policy]
        if capability not in allowed_capabilities:
            reason = (
                "source_policy_notebook_only"
                if policy == SourcePolicy.NOTEBOOK_ONLY
                else "source_policy_capability_not_allowed"
            )
            return ToolPolicyDecision(allowed=False, reason=reason)

        return ToolPolicyDecision(allowed=True, reason="allowed")
