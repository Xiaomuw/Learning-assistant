"""Audit locally built candidate images; never pull or publish application images."""
import argparse
import json
from pathlib import Path
import subprocess

from scan_container_bases import classify_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trivy", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    outcomes = []
    for name in ("la-candidate-backend:ci", "la-candidate-frontend:ci"):
        identity = subprocess.check_output(["docker", "image", "inspect", name, "--format", "{{.Id}}"], text=True).strip()
        stem = name.split(":")[0]
        report = args.output_dir / f"{stem}-vulnerabilities.json"
        common = [args.trivy, "image", "--image-src", "docker", "--no-progress"]
        result = subprocess.run(common + ["--scanners", "vuln", "--severity", "HIGH,CRITICAL", "--exit-code", "10",
                                         "--format", "json", "--output", str(report), identity], check=False)
        outcome = classify_report(result.returncode, report)
        outcome.update(image=name, image_id=identity)
        for suffix, flags in (("licenses", ["--scanners", "license", "--license-full", "--format", "json"]),
                              ("sbom", ["--format", "cyclonedx"])):
            extra = subprocess.run(common + flags + ["--output", str(args.output_dir / f"{stem}-{suffix}.json"), identity], check=False)
            if extra.returncode != 0:
                outcome["status"] = "scan_error"
        outcomes.append(outcome)
        print(json.dumps(outcome), flush=True)
    (args.output_dir / "summary.json").write_text(json.dumps(outcomes, indent=2) + "\n")
    if any(row["status"] == "scan_error" for row in outcomes):
        return 2
    return 1 if any(row["status"] == "findings" for row in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
