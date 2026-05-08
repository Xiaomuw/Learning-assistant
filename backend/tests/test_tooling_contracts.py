from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.services.tooling.executor import ToolExecutor
from app.services.tooling.policy import ToolPolicyResolver
from app.services.tooling.registry import build_default_tool_registry
from app.services.tooling.schemas import ToolExecutionRequest, ToolPolicyDecision, ToolRiskLevel
from app.shared.schemas.agent_graphs import SourcePolicy, ToolCapability, ToolStatus
from app.shared.schemas.contracts import RetrievalDiagnostics, RetrievedDocument


class ToolingContractsTest(unittest.TestCase):
    def test_registry_returns_tavily_as_web_search_provider(self) -> None:
        registry = build_default_tool_registry()
        tools = registry.find_by_capability(ToolCapability.WEB_SEARCH)

        self.assertTrue(any(item.provider == "tavily" for item in tools))
        self.assertTrue(all(item.capability == ToolCapability.WEB_SEARCH for item in tools))

    def test_registry_returns_notebook_retrieve_provider(self) -> None:
        registry = build_default_tool_registry()
        tools = registry.find_by_capability(ToolCapability.NOTEBOOK_RETRIEVE)

        self.assertTrue(any(item.provider == "notebook" for item in tools))
        self.assertTrue(all(item.capability == ToolCapability.NOTEBOOK_RETRIEVE for item in tools))

    def test_policy_blocks_web_search_for_notebook_only(self) -> None:
        decision = ToolPolicyResolver().resolve(
            source_policy=SourcePolicy.NOTEBOOK_ONLY,
            capability=ToolCapability.WEB_SEARCH,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "source_policy_notebook_only")

    def test_policy_allows_notebook_retrieve_for_notebook_only(self) -> None:
        decision = ToolPolicyResolver().resolve(
            source_policy=SourcePolicy.NOTEBOOK_ONLY,
            capability=ToolCapability.NOTEBOOK_RETRIEVE,
        )

        self.assertTrue(decision.allowed)

    def test_policy_blocks_open_capabilities_for_notebook_plus_external(self) -> None:
        for capability in (ToolCapability.SQL_READ, ToolCapability.CODE_EXECUTE, ToolCapability.FILE_PARSE):
            with self.subTest(capability=capability.value):
                decision = ToolPolicyResolver().resolve(
                    source_policy=SourcePolicy.NOTEBOOK_PLUS_EXTERNAL,
                    capability=capability,
                )

                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, "source_policy_capability_not_allowed")

    def test_policy_allows_web_search_for_notebook_plus_external(self) -> None:
        decision = ToolPolicyResolver().resolve(
            source_policy=SourcePolicy.NOTEBOOK_PLUS_EXTERNAL,
            capability=ToolCapability.WEB_SEARCH,
        )

        self.assertTrue(decision.allowed)

    def test_policy_blocks_high_risk_tools_in_test_mode(self) -> None:
        decision = ToolPolicyResolver().resolve(
            source_policy=SourcePolicy.OPEN_TOOLS,
            capability=ToolCapability.SQL_READ,
            risk_level=ToolRiskLevel.HIGH,
            test_mode=True,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "test_mode_blocks_high_risk_tool")

    def test_policy_blocks_tenant_scope_mismatch(self) -> None:
        decision = ToolPolicyResolver().resolve(
            source_policy=SourcePolicy.OPEN_TOOLS,
            capability=ToolCapability.NOTEBOOK_RETRIEVE,
            tenant_scope="tenant-a",
            tenant_id="tenant-b",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "tenant_scope_mismatch")

    def test_policy_blocks_write_tools_by_default(self) -> None:
        decision = ToolPolicyResolver().resolve(
            source_policy=SourcePolicy.OPEN_TOOLS,
            capability=ToolCapability.CODE_EXECUTE,
            risk_level=ToolRiskLevel.WRITE,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "write_tools_disabled")

    def test_policy_allows_open_tool_capability_after_rule_chain_passes(self) -> None:
        decision = ToolPolicyResolver().resolve(
            source_policy=SourcePolicy.OPEN_TOOLS,
            capability=ToolCapability.CODE_EXECUTE,
            risk_level=ToolRiskLevel.MEDIUM,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "allowed")

    def test_policy_blocks_invalid_source_policy(self) -> None:
        decision = ToolPolicyResolver().resolve(
            source_policy="unknown_policy",
            capability=ToolCapability.NOTEBOOK_RETRIEVE,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "invalid_source_policy")

    def test_custom_policy_rule_short_circuits_default_chain(self) -> None:
        class CustomBlockRule:
            def decide(self, context):
                return ToolPolicyDecision(allowed=False, reason="custom_block")

        decision = ToolPolicyResolver(rules=(CustomBlockRule(),)).resolve(
            source_policy=SourcePolicy.OPEN_TOOLS,
            capability=ToolCapability.NOTEBOOK_RETRIEVE,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "custom_block")

    def test_custom_policy_rule_order_is_respected(self) -> None:
        class FirstRule:
            def decide(self, context):
                return ToolPolicyDecision(allowed=False, reason="first_rule")

        class SecondRule:
            def decide(self, context):
                return ToolPolicyDecision(allowed=False, reason="second_rule")

        decision = ToolPolicyResolver(rules=(FirstRule(), SecondRule())).resolve(
            source_policy=SourcePolicy.OPEN_TOOLS,
            capability=ToolCapability.NOTEBOOK_RETRIEVE,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "first_rule")

    def test_executor_blocks_before_provider_execution(self) -> None:
        executor = ToolExecutor(
            registry=build_default_tool_registry(),
            policy_resolver=ToolPolicyResolver(),
        )
        result = executor.execute(
            ToolExecutionRequest(
                capability=ToolCapability.WEB_SEARCH,
                input={"query": "HTTP/3"},
                input_summary="HTTP/3",
                source_policy=SourcePolicy.NOTEBOOK_ONLY.value,
            ),
            provider="tavily",
        )

        self.assertEqual(result.status, ToolStatus.BLOCKED)
        self.assertEqual(result.provider, "tavily")
        self.assertEqual(result.error, "source_policy_notebook_only")

    def test_notebook_retrieve_adapter_returns_verified_evidence(self) -> None:
        class FakeRagResult:
            raw_docs = [RetrievedDocument(doc_id="raw-1", content="raw", score=0.4)]
            docs = [
                RetrievedDocument(
                    doc_id="doc-1",
                    content="HTTP 默认端口是 80。",
                    metadata={"source_id": "chunk-1"},
                    score=0.9,
                )
            ]
            diagnosis = RetrievalDiagnostics(query="HTTP", hit_count=1, top_score=0.9, diagnosis="ready")
            contextual_query = "HTTP"
            rag_ready = True
            relevance = {"kept_count": 1, "discarded_count": 0, "reason": "ready"}

        executor = ToolExecutor(
            registry=build_default_tool_registry(),
            policy_resolver=ToolPolicyResolver(),
        )
        with patch("app.services.tooling.adapters.notebook.retrieve_context", return_value=FakeRagResult()):
            result = executor.execute(
                ToolExecutionRequest(
                    capability=ToolCapability.NOTEBOOK_RETRIEVE,
                    input={"query": "HTTP", "subject_id": "network"},
                    input_summary="HTTP",
                    source_policy=SourcePolicy.NOTEBOOK_ONLY.value,
                )
            )

        self.assertEqual(result.status, ToolStatus.SUCCESS)
        self.assertEqual(result.provider, "notebook")
        self.assertEqual(result.output["verified_count"], 1)
        self.assertEqual(result.evidence[0].source_type, "notebook")
        self.assertEqual(result.evidence[0].text, "HTTP 默认端口是 80。")


if __name__ == "__main__":
    unittest.main()
