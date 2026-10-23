"""Scan pinned public base images; preserve findings and fail closed on scan errors."""

import argparse
import json
from pathlib import Path
import re
import subprocess


def classify_report(returncode: int, report: Path) -> dict:
    if returncode not in (0, 10):
        return {"status": "scan_error", "scanner_exit_code": returncode}
    try:
        data = json.loads(report.read_text())
        results = data["Results"]
        if not isinstance(results, list):
            raise ValueError("Results must be a list")
        findings = [v for result in results for v in result.get("Vulnerabilities", [])]
        counts = {severity: sum(v["Severity"] == severity for v in findings)
                  for severity in ("HIGH", "CRITICAL")}
        if any(v["Severity"] not in counts for v in findings):
            raise ValueError("Unexpected severity in filtered report")
        total = sum(counts.values())
        if (returncode == 10) != bool(total):
            raise ValueError("Scanner exit disagrees with report")
        distinct = len({v["VulnerabilityID"] for v in findings})
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {"status": "scan_error", "scanner_exit_code": returncode}
    return {"status": "findings" if total else "pass", "scanner_exit_code": returncode,
            "package_advisory_counts": counts,
            "distinct_advisories": distinct}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trivy", default="trivy")
    parser.add_argument("--inventory", type=Path, default=Path(__file__).resolve().parents[1]
                        / "docs/audits/container-digests-2026-10-23.json")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    images = json.loads(args.inventory.read_text())["images"]
    if not images or any(not re.fullmatch(r"sha256:[0-9a-f]{64}", i["digest"]) for i in images):
        raise ValueError("Inventory must contain full immutable image digests")
    # A fresh directory prevents a failed scan from accidentally reusing old reports.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    summary = []
    for index, image in enumerate(images):
        reference = image["image"] + "@" + image["digest"]
        report = args.output_dir / f"image-{index}.json"
        command = [args.trivy, "image", "--image-src", "remote", "--platform", "linux/amd64",
                   "--scanners", "vuln", "--severity", "HIGH,CRITICAL", "--exit-code", "10",
                   "--format", "json", "--output", str(report), "--no-progress", reference]
        try:
            result = subprocess.run(command, check=False)
            outcome = classify_report(result.returncode, report)
        except OSError:
            outcome = {"status": "scan_error", "scanner_exit_code": None}
        outcome.update(image=reference, report=report.name)
        summary.append(outcome)
        print(json.dumps(outcome), flush=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if any(item["status"] == "scan_error" for item in summary):
        return 2
    return 1 if any(item["status"] == "findings" for item in summary) else 0


if __name__ == "__main__":
    raise SystemExit(main())
