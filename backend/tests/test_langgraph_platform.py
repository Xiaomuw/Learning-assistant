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
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-more-than-32-characters")


class LangGraphPlatformConfigTest(unittest.TestCase):
    def test_langgraph_json_points_to_platform_graph_and_lifespan_app(self) -> None:
        config = json.loads((BACKEND_ROOT / "langgraph.json").read_text(encoding="utf-8"))

        self.assertEqual(
            config["graphs"]["learning_assistant"],
            "./app/orchestration/platform/graph.py:graph",
        )
        self.assertEqual(
            config["http"]["app"],
            "./app/orchestration/platform/webapp.py:app",
        )
        self.assertEqual(config["dependencies"], ["."])

    def test_platform_graph_imports_as_compiled_graph(self) -> None:
        from app.orchestration.platform.graph import graph

        self.assertTrue(hasattr(graph, "invoke"))
        self.assertTrue(hasattr(graph, "stream"))

    def test_platform_lifespan_app_is_importable_without_public_api_routes(self) -> None:
        from app.orchestration.platform.webapp import app

        routes = {route.path for route in app.routes}
        self.assertIn("/health", routes)
        self.assertNotIn("/api/chat", routes)


if __name__ == "__main__":
    unittest.main()
