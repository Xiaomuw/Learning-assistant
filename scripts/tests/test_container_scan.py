"""Validate scan-result gates with synthetic reports, not claims about real images."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "scan_container_bases", Path(__file__).resolve().parents[1] / "scan_container_bases.py")
assert spec and spec.loader
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class ContainerScanGateTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.report = Path(directory.name) / "report.json"

    def write_report(self, findings: list) -> None:
        self.report.write_text(json.dumps({"Results": [{"Vulnerabilities": findings}]}))

    def test_clean_scan_passes(self) -> None:
        self.write_report([])
        self.assertEqual(scanner.classify_report(0, self.report)["status"], "pass")

    def test_findings_fail_with_duplicate_aware_counts(self) -> None:
        self.write_report([{"Severity": "HIGH", "VulnerabilityID": "SYNTHETIC-1"},
                           {"Severity": "HIGH", "VulnerabilityID": "SYNTHETIC-1"}])
        result = scanner.classify_report(10, self.report)
        self.assertEqual(result["status"], "findings")
        self.assertEqual(result["package_advisory_counts"]["HIGH"], 2)
        self.assertEqual(result["distinct_advisories"], 1)

    def test_scanner_failure_cannot_reuse_a_clean_report(self) -> None:
        self.write_report([])
        self.assertEqual(scanner.classify_report(1, self.report)["status"], "scan_error")

    def test_missing_and_malformed_reports_fail_closed(self) -> None:
        self.assertEqual(scanner.classify_report(0, self.report)["status"], "scan_error")
        for text in ("not-json", "{}", '{"Results": null}', '{"Results": [null]}'):
            with self.subTest(text=text):
                self.report.write_text(text)
                self.assertEqual(scanner.classify_report(0, self.report)["status"], "scan_error")
        self.write_report([{"Severity": "HIGH"}])
        self.assertEqual(scanner.classify_report(10, self.report)["status"], "scan_error")

    def test_exit_code_and_findings_must_agree(self) -> None:
        self.write_report([])
        self.assertEqual(scanner.classify_report(10, self.report)["status"], "scan_error")
        self.write_report([{"Severity": "CRITICAL", "VulnerabilityID": "SYNTHETIC-2"}])
        self.assertEqual(scanner.classify_report(0, self.report)["status"], "scan_error")


if __name__ == "__main__":
    unittest.main()
