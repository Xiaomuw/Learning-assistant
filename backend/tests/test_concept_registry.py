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

from app.knowledge.concept_registry import ConceptRegistry  # noqa: E402


class ConceptRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ConceptRegistry()

    def test_loads_all_four_taxonomies(self) -> None:
        self.assertEqual(
            set(self.registry.subjects),
            {
                "data-structure",
                "computer-network",
                "operating-system",
                "computer-organization",
            },
        )
        self.assertGreaterEqual(len(self.registry.concepts), 40)
        for node in self.registry.concepts.values():
            self.assertTrue(node.subject_id)
            self.assertTrue(node.chapter_id)
            self.assertTrue(node.topic_id)
            self.assertTrue(node.concept_id)
            self.assertTrue(node.aliases)

    def test_alias_match_returns_canonical_concept_id(self) -> None:
        match = self.registry.match_query("HTTP 默认端口是多少？")

        self.assertEqual(match.status, "matched")
        self.assertEqual(match.subject_id, "computer-network")
        self.assertEqual(match.concept_id, "computer-network.application.http-https")
        self.assertGreaterEqual(match.confidence, 0.7)

    def test_subject_only_when_subject_is_clear_but_concept_is_not(self) -> None:
        match = self.registry.match_query("计算机网络这门课应该怎么复习？")

        self.assertEqual(match.status, "subject_only")
        self.assertEqual(match.subject_id, "computer-network")
        self.assertFalse(match.concept_id)

    def test_unmapped_when_no_taxonomy_signal(self) -> None:
        match = self.registry.match_query("帮我看看这句话有没有语病")

        self.assertEqual(match.status, "unmapped")
        self.assertFalse(match.concept_id)


if __name__ == "__main__":
    unittest.main()
