"""
LangGraph Platform graph export.

This module is loaded by ``backend/langgraph.json``. The exported graph name
remains ``learning_assistant`` for platform compatibility, but the compiled
graph is the production ``LearningOrchestratorGraph``.
"""

from __future__ import annotations

from dotenv import load_dotenv

from app.orchestration.graphs.orchestrator.graph import build_graph

load_dotenv()

graph = build_graph().compile()

__all__ = ["graph"]
