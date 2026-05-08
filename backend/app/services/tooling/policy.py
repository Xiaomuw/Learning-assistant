from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

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


@dataclass(frozen=True)
class ToolPolicyContext:
    source_policy: SourcePolicy | str
    capability: ToolCapability
    risk_level: ToolRiskLevel
    tenant_scope: str | None = None
    tenant_id: str | None = None
    test_mode: bool = False
    allow_write_tools: bool = False


class ToolPolicyRule(Protocol):
    """Single authorization rule in the capability policy chain."""

    def decide(self, context: ToolPolicyContext) -> ToolPolicyDecision | None:
        """Return a blocking/allowing decision, or defer to the next rule."""


class TenantScopeRule:
    def decide(self, context: ToolPolicyContext) -> ToolPolicyDecision | None:
        if context.tenant_scope and context.tenant_id and context.tenant_scope != context.tenant_id:
            return ToolPolicyDecision(allowed=False, reason="tenant_scope_mismatch")
        return None


class TestModeRiskRule:
    def decide(self, context: ToolPolicyContext) -> ToolPolicyDecision | None:
        if context.test_mode and context.risk_level in {ToolRiskLevel.WRITE, ToolRiskLevel.HIGH}:
            return ToolPolicyDecision(allowed=False, reason="test_mode_blocks_high_risk_tool")
        return None


class WriteToolRule:
    def decide(self, context: ToolPolicyContext) -> ToolPolicyDecision | None:
        if context.risk_level == ToolRiskLevel.WRITE and not context.allow_write_tools:
            return ToolPolicyDecision(allowed=False, reason="write_tools_disabled")
        return None


class SourcePolicyCapabilityRule:
    def decide(self, context: ToolPolicyContext) -> ToolPolicyDecision | None:
        try:
            policy = SourcePolicy(str(context.source_policy or SourcePolicy.OPEN_TOOLS.value))
        except ValueError:
            return ToolPolicyDecision(allowed=False, reason="invalid_source_policy")
        allowed_capabilities = _SOURCE_POLICY_CAPABILITIES[policy]
        if context.capability not in allowed_capabilities:
            reason = (
                "source_policy_notebook_only"
                if policy == SourcePolicy.NOTEBOOK_ONLY
                else "source_policy_capability_not_allowed"
            )
            return ToolPolicyDecision(allowed=False, reason=reason)
        return None


class AllowToolPolicyRule:
    def decide(self, context: ToolPolicyContext) -> ToolPolicyDecision | None:
        return ToolPolicyDecision(allowed=True, reason="allowed")


DEFAULT_TOOL_POLICY_RULES: tuple[ToolPolicyRule, ...] = (
    TenantScopeRule(),
    TestModeRiskRule(),
    WriteToolRule(),
    SourcePolicyCapabilityRule(),
    AllowToolPolicyRule(),
)


class ToolPolicyResolver:
    """Decides whether a graph may use a capability before provider execution."""

    def __init__(
        self,
        *,
        allow_write_tools: bool = False,
        rules: Sequence[ToolPolicyRule] | None = None,
    ) -> None:
        self.allow_write_tools = allow_write_tools
        self.rules = tuple(rules or DEFAULT_TOOL_POLICY_RULES)

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
        context = ToolPolicyContext(
            source_policy=source_policy,
            capability=capability,
            risk_level=risk_level,
            tenant_scope=tenant_scope,
            tenant_id=tenant_id,
            test_mode=test_mode,
            allow_write_tools=self.allow_write_tools,
        )
        for rule in self.rules:
            decision = rule.decide(context)
            if decision is not None:
                return decision
        return ToolPolicyDecision(allowed=True, reason="allowed")
