from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.orchestration.graphs.orchestrator.route_decider import BoundaryRoute, decide_route
from app.orchestration.graphs.shared.schemas import GraphType, SourcePolicy, ToolCapability


class RouteDeciderTest(unittest.TestCase):
    def test_simple_fact_routes_to_direct_response_without_qagraph(self) -> None:
        decision = decide_route(
            {
                "user_id": "u1",
                "user_message": "1+1等于几",
                "runtime_context": {"available_capabilities": [ToolCapability.WEB_SEARCH.value]},
            }
        )

        self.assertEqual(decision.route, BoundaryRoute.SIMPLE_FACT)
        self.assertEqual(decision.target_graph_type, GraphType.ORCHESTRATOR)
        self.assertTrue(decision.bypass_qagraph)

    def test_practice_generation_bypasses_qagraph_by_default(self) -> None:
        decision = decide_route({"user_id": "u1", "user_message": "帮我出几道加减法题"})

        self.assertEqual(decision.route, BoundaryRoute.PRACTICE_GENERATION)
        self.assertEqual(decision.target_graph_type, GraphType.QUESTION_GENERATION)
        self.assertTrue(decision.bypass_qagraph)

    def test_context_dependent_practice_requires_context(self) -> None:
        decision = decide_route({"user_id": "u1", "user_message": "根据我的笔记帮我出几道 HTTP 题"})

        self.assertEqual(decision.route, BoundaryRoute.PRACTICE_GENERATION)
        self.assertEqual(decision.target_graph_type, GraphType.ORCHESTRATOR)
        self.assertIn("上下文不足", decision.reason)

    def test_meta_tool_usage_routes_to_trace_reader(self) -> None:
        decision = decide_route(
            {
                "user_id": "u1",
                "user_message": "刚刚有联网搜索吗",
                "messages": [
                    {
                        "role": "assistant",
                        "toolInvocationTrace": {
                            "toolCallCount": 0,
                            "toolCalls": [],
                            "didUseWebSearch": False,
                            "didUseAnyTool": False,
                        },
                    }
                ],
            }
        )

        self.assertEqual(decision.route, BoundaryRoute.META_TOOL_USAGE)
        self.assertEqual(decision.target_graph_type, GraphType.ORCHESTRATOR)
        self.assertTrue(decision.uses_trace)
        self.assertTrue(decision.policy.has_trace)

    def test_realtime_or_fresh_allows_web_when_policy_has_capability(self) -> None:
        decision = decide_route(
            {
                "user_id": "u1",
                "user_message": "今年 GPT 发布到哪个版本了",
                "source_policy": SourcePolicy.OPEN_TOOLS.value,
                "runtime_context": {"available_capabilities": [ToolCapability.WEB_SEARCH.value]},
            }
        )

        self.assertEqual(decision.route, BoundaryRoute.REALTIME_OR_FRESH)
        self.assertEqual(decision.target_graph_type, GraphType.QA)
        self.assertTrue(decision.policy.allow_web)

    def test_realtime_or_fresh_without_web_stays_direct_and_limited(self) -> None:
        decision = decide_route(
            {
                "user_id": "u1",
                "user_message": "今年 GPT 发布到哪个版本了",
                "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                "runtime_context": {"available_capabilities": [ToolCapability.WEB_SEARCH.value]},
            }
        )

        self.assertEqual(decision.route, BoundaryRoute.REALTIME_OR_FRESH)
        self.assertEqual(decision.target_graph_type, GraphType.ORCHESTRATOR)
        self.assertFalse(decision.policy.allow_web)
        self.assertTrue(decision.policy.notebook_only)

    def test_simple_fact_with_notebook_only_policy_stays_direct_no_web(self) -> None:
        decision = decide_route(
            {
                "user_id": "u1",
                "user_message": "1+1等于几",
                "source_policy": SourcePolicy.NOTEBOOK_ONLY.value,
                "runtime_context": {"available_capabilities": [ToolCapability.WEB_SEARCH.value]},
            }
        )

        self.assertEqual(decision.route, BoundaryRoute.SIMPLE_FACT)
        self.assertEqual(decision.target_graph_type, GraphType.ORCHESTRATOR)
        self.assertFalse(decision.policy.allow_web)
        self.assertTrue(decision.policy.notebook_only)

    def test_explanation_or_tutoring_enters_qagraph(self) -> None:
        decision = decide_route({"user_id": "u1", "user_message": "详细解释 TCP 三次握手"})

        self.assertEqual(decision.route, BoundaryRoute.QA_GRAPH)
        self.assertEqual(decision.target_graph_type, GraphType.QA)
        self.assertFalse(decision.bypass_qagraph)


if __name__ == "__main__":
    unittest.main()
