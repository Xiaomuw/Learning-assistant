from __future__ import annotations

import json
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

from app.orchestration.graphs.shared.state import BaseLearningState
from app.shared.schemas.agent_graphs import (
    ConceptRef,
    EvidenceChunk,
    FinalResponse,
    GraphError,
    GraphType,
    LearningEvent,
    SourceLevel,
    SourcePolicy,
    ToolCapability,
    ToolResult,
    ToolStatus,
)


class AgentGraphContractsTest(unittest.TestCase):
    def test_core_schemas_are_serializable(self) -> None:
        concept = ConceptRef(concept_id="http", name="HTTP", confidence=0.95, source="router")
        evidence = EvidenceChunk(
            source_type="notebook",
            source_id="chunk-1",
            text="HTTP 是应用层协议。",
            score=0.88,
            concepts=[concept],
        )
        tool_result = ToolResult(
            tool_id="web_search:tavily",
            provider="tavily",
            capability=ToolCapability.WEB_SEARCH,
            status=ToolStatus.SUCCESS,
            input_summary="HTTP/3 browser support",
            evidence=[evidence],
            latency_ms=12,
        )
        event = LearningEvent(
            event_type="concept_explained",
            user_id="u1",
            concept_id="http",
            graph_run_id="run-1",
            payload={"source": "qa"},
        )
        response = FinalResponse(
            answer="HTTP 是应用层协议。",
            source_level=SourceLevel.MODEL,
            concepts=[concept],
            evidence_refs=[evidence.id],
            coach_actions=["explain"],
            mastery_signals={"confidence": 0.8},
        )
        error = GraphError(code="x", message="safe error", node="node")

        payload = {
            "concept": concept.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
            "tool_result": tool_result.model_dump(mode="json"),
            "event": event.model_dump(mode="json"),
            "response": response.model_dump(mode="json"),
            "error": error.model_dump(mode="json"),
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertIn("HTTP", encoded)
        self.assertIn("web_search", encoded)

    def test_base_learning_state_is_checkpoint_friendly(self) -> None:
        state: BaseLearningState = {
            "run_id": "run-1",
            "tenant_id": None,
            "user_id": "u1",
            "notebook_id": "general",
            "course_id": None,
            "thread_id": "thread-1",
            "graph_type": GraphType.QA.value,
            "graph_version": "0.1.0",
            "source_policy": SourcePolicy.OPEN_TOOLS.value,
            "user_message": "什么是 HTTP？",
            "messages": [{"role": "user", "content": "什么是 HTTP？"}],
            "concepts": [],
            "evidence": [],
            "tool_results": [],
            "learning_events": [],
            "final_response": {},
            "errors": [],
        }

        encoded = json.dumps(state, ensure_ascii=False)
        self.assertIn("run-1", encoded)
        self.assertNotIn("SessionLocal", encoded)


if __name__ == "__main__":
    unittest.main()

