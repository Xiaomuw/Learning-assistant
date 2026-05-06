from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.shared.schemas.agent_graphs import ToolCapability


class ToolRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    WRITE = "write"


class ToolRegistration(BaseModel):
    tool_id: str
    provider: str
    capability: ToolCapability
    description: str = ""
    enabled: bool = True
    tenant_scope: str | None = None
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    version: str = "0.1.0"


class ToolExecutionRequest(BaseModel):
    capability: ToolCapability
    input: dict[str, Any] = Field(default_factory=dict)
    input_summary: str = ""
    user_id: str = ""
    tenant_id: str | None = None
    source_policy: str = "open_tools"
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    test_mode: bool = False
    runtime_context: dict[str, Any] = Field(default_factory=dict)


class ToolPolicyDecision(BaseModel):
    allowed: bool
    reason: str = ""

