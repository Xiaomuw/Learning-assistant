from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_question_bank_provenance import (
    MIRRORS,
    REQUIRED_LEDGER_KEYS,
    audit,
)


class SourceReviewAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.data_dir = self.dir / "questions"
        self.data_dir.mkdir()
        self.canonical = self.data_dir / "all_408.json"
        self.ledger = self.dir / "review.csv"
        self.question = {
            "question_id": "synthetic-example-1",
            "concept_id": "data-structure.example",
            "difficulty": "basic",
            "stem": "Independent test question",
            "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "answer": "A",
            "explanation": "Independent test explanation",
        }
        self.canonical.write_text(
            json.dumps([self.question], ensure_ascii=False), encoding="utf-8"
        )
        for name in MIRRORS:
            rows = [self.question] if name == MIRRORS[0] else []
            (self.data_dir / name).write_text(
                json.dumps(rows, ensure_ascii=False), encoding="utf-8"
            )
        self.write_ledger("REVIEW_REQUIRED")

    def write_ledger(
        self,
        status: str,
        permission: str = "",
        evidence: str = "",
    ) -> None:
        with self.ledger.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(REQUIRED_LEDGER_KEYS))
            writer.writeheader()
            writer.writerow(
                {
                    "question_id": "synthetic-example-1",
                    "acquisition_method": "AI_WEB_SEARCH_REORGANIZED",
                    "review_status": status,
                    "license_or_permission": permission,
                    "evidence_ref": evidence,
                }
            )

    def report(self) -> dict:
        return audit(self.canonical, self.data_dir, self.ledger)

    def test_all_unverified_blocks_release_but_not_structure(self) -> None:
        report = self.report()
        self.assertEqual(report["structural_error_count"], 0)
        self.assertEqual(report["uncleared_questions"], 1)
        self.assertFalse(report["release_gate_passes"])

    def retire_corpus(self) -> None:
        self.canonical.unlink()
        for name in MIRRORS:
            (self.data_dir / name).unlink()

    def test_removed_current_corpus_keeps_history_ledger_without_orphan_errors(self) -> None:
        self.retire_corpus()
        report = self.report()
        self.assertEqual(report["dataset_state"], "retired_from_current_tree")
        self.assertEqual(report["canonical_questions"], 0)
        self.assertEqual(report["ledger_rows"], 1)
        self.assertEqual(report["unresolved_historical_ledger_entries"], 1)
        self.assertEqual(report["structural_error_count"], 0)
        self.assertTrue(report["current_tree_data_boundary_passes"])
        self.assertTrue(report["historical_review_required"])
        self.assertFalse(report["release_gate_passes"])

    def test_partial_deletion_is_rejected(self) -> None:
        self.canonical.unlink()
        report = self.report()
        self.assertGreater(report["structural_error_count"], 0)
        self.assertFalse(report["current_tree_data_boundary_passes"])

    def test_unexpected_public_json_is_rejected_even_when_originals_removed(self) -> None:
        self.retire_corpus()
        (self.data_dir / "unreviewed-extra.json").write_text("[]", encoding="utf-8")
        report = self.report()
        self.assertGreater(report["structural_error_count"], 0)
        self.assertFalse(report["current_tree_data_boundary_passes"])

    def test_missing_historical_ledger_is_not_silently_accepted(self) -> None:
        self.retire_corpus()
        self.ledger.unlink()
        report = self.report()
        self.assertGreater(report["structural_error_count"], 0)

    def test_mirror_drift_is_detected(self) -> None:
        changed = {**self.question, "answer": "B"}
        (self.data_dir / MIRRORS[0]).write_text(
            json.dumps([changed]), encoding="utf-8"
        )
        self.assertGreater(self.report()["structural_error_count"], 0)

    def test_cleared_requires_permission_evidence(self) -> None:
        self.write_ledger("CLEARED")
        self.assertGreater(self.report()["structural_error_count"], 0)
        self.write_ledger(
            "CLEARED",
            permission="documented permission for synthetic test fixture",
            evidence="test-only-local-evidence",
        )
        report = self.report()
        self.assertEqual(report["structural_error_count"], 0)
        self.assertTrue(report["release_gate_passes"])


if __name__ == "__main__":
    unittest.main()
