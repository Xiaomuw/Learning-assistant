#!/usr/bin/env python3
"""Audit current question-bank files and a separate historical provenance ledger.

This is a structural and bookkeeping checker, NOT a copyright determination.
The public source tree may contain the old question corpus (legacy PR state) or
may have removed all five files (after the data-separation PR). In both cases,
the 530-ID historical review ledger must remain readable and truthful.

--release-gate deliberately fails on a retired/uncleared historical corpus:
absence from HEAD is not proof that Git history or third-party copies are safe.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "practice_questions"
CANONICAL = DATA_DIR / "all_408.json"
MIRRORS = (
    "data_structure.json",
    "operating_system.json",
    "computer_network.json",
    "computer_organization.json",
)
LEDGER = ROOT / "data" / "provenance" / "408-source-review.csv"
REQUIRED_QUESTION_KEYS = frozenset(
    {"question_id", "concept_id", "stem", "options", "answer", "explanation"}
)
REQUIRED_LEDGER_KEYS = frozenset(
    {
        "question_id",
        "acquisition_method",
        "source_url",
        "source_title",
        "rights_holder",
        "license_or_permission",
        "evidence_ref",
        "review_status",
        "notes",
    }
)
VALID_STATUSES = frozenset({"REVIEW_REQUIRED", "CLEARED", "REPLACE", "REMOVE"})


def _read_questions(path: Path, problems: list[str]) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        problems.append(f"Could not read JSON file {path.name}: {type(exc).__name__}")
        return []
    if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
        problems.append(f"{path.name} must be an array of JSON objects")
        return []
    return payload


def audit(
    canonical_path: Path = CANONICAL,
    mirror_dir: Path = DATA_DIR,
    ledger_path: Path = LEDGER,
) -> dict:
    """Check file boundaries and historical review bookkeeping.

    An owner-entered CLEARED state is not proof of copyright permission.
    Only identifiers/statuses are shown; no question wording or evidence files
    are printed.
    """
    problems: list[str] = []
    canonical_present = canonical_path.is_file()
    mirror_paths = [mirror_dir / name for name in MIRRORS]
    any_mirror_present = any(p.exists() for p in mirror_paths)
    retired_from_current_tree = not canonical_present and not any_mirror_present

    if not canonical_present and any_mirror_present:
        problems.append("Canonical question file is missing while a mirror still exists")
    expected_paths = {canonical_path.resolve(), *(p.resolve() for p in mirror_paths)}
    if mirror_dir.exists():
        for path in sorted(mirror_dir.glob("*.json")):
            if path.resolve() not in expected_paths:
                problems.append(f"Unexpected public JSON corpus in question directory: {path.name}")

    canonical = _read_questions(canonical_path, problems) if canonical_present else []
    question_by_id: dict[str, dict] = {}
    subjects: Counter[str] = Counter()
    without_provenance = 0
    for index, question in enumerate(canonical, start=1):
        qid = str(question.get("question_id") or "").strip()
        if not qid:
            problems.append(f"Missing question_id in canonical row {index}")
            continue
        if qid in question_by_id:
            problems.append(f"Duplicate canonical ID: {qid}")
        question_by_id[qid] = question
        missing = REQUIRED_QUESTION_KEYS - set(question)
        if missing:
            problems.append(f"{qid}: missing required keys {sorted(missing)}")
        subjects[str(question.get("concept_id") or "unknown").split(".")[0]] += 1
        keys = (
            "source_url", "source_name", "source_title", "rights_holder",
            "license", "license_or_permission", "prompt", "model_id",
        )
        if not any(str(question.get(key) or "").strip() for key in keys):
            without_provenance += 1

    mirror_ids: set[str] = set()
    mirror_count = 0
    for path in mirror_paths:
        if not path.is_file():
            if canonical_present:
                problems.append(f"Missing expected subject mirror: {path.name}")
            continue
        rows = _read_questions(path, problems)
        for row in rows:
            mirror_count += 1
            qid = str(row.get("question_id") or "").strip()
            if qid in mirror_ids:
                problems.append(f"Duplicate ID across mirrors: {qid}")
            mirror_ids.add(qid)
            if qid not in question_by_id:
                problems.append(f"Mirror {path.name} has an unknown ID: {qid}")
            elif row != question_by_id[qid]:
                problems.append(f"Mirror mismatch for ID: {qid}")
    for qid in question_by_id.keys() - mirror_ids:
        problems.append(f"Canonical ID missing from mirrors: {qid}")

    statuses: Counter[str] = Counter()
    ledger_rows: dict[str, dict] = {}
    try:
        with ledger_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing_headers = REQUIRED_LEDGER_KEYS - set(reader.fieldnames or [])
            if missing_headers:
                problems.append(f"Ledger missing fields: {sorted(missing_headers)}")
            else:
                for row in reader:
                    qid = str(row.get("question_id") or "").strip()
                    status = str(row.get("review_status") or "").strip()
                    if not qid or qid in ledger_rows:
                        problems.append(f"Blank/duplicate ledger ID: {qid or '(blank)'}")
                        continue
                    ledger_rows[qid] = row
                    statuses[status or "(blank)"] += 1
                    if status not in VALID_STATUSES:
                        problems.append(f"{qid}: invalid review_status: {status}")
                    if status == "CLEARED" and not (
                        str(row.get("license_or_permission") or "").strip()
                        and str(row.get("evidence_ref") or "").strip()
                    ):
                        problems.append(
                            f"{qid}: CLEARED requires permission basis and evidence reference"
                        )
    except (OSError, UnicodeError, csv.Error) as exc:
        problems.append(f"Could not read review ledger: {type(exc).__name__}")

    # When the current corpus exists, every ID must have a matching ledger
    # entry. Once all five corpus files are removed, the 530-ID ledger remains
    # historical metadata and must NOT be treated as orphaned source data.
    if not retired_from_current_tree:
        for qid in question_by_id.keys() - ledger_rows.keys():
            problems.append(f"Missing ledger row: {qid}")
        for qid in ledger_rows.keys() - question_by_id.keys():
            problems.append(f"Ledger references unknown current ID: {qid}")

    cleared_ids = {
        qid for qid, row in ledger_rows.items()
        if row.get("review_status") == "CLEARED"
        and str(row.get("license_or_permission") or "").strip()
        and str(row.get("evidence_ref") or "").strip()
    }
    cleared_current = len(cleared_ids & question_by_id.keys())
    unresolved_historical = len(ledger_rows.keys() - cleared_ids)
    current_boundary_passes = not problems and (
        retired_from_current_tree
        or (bool(question_by_id) and cleared_current == len(question_by_id))
    )

    # A broader release declaration requires separate history/legal/dependency
    # review, which this script cannot prove. Keep it blocked when the old
    # corpus is retired and the historical review ledger is unresolved.
    release_gate_passes = (
        bool(question_by_id)
        and cleared_current == len(question_by_id)
        and not problems
    )
    return {
        "dataset_state": "retired_from_current_tree" if retired_from_current_tree
                         else "present_or_partially_removed",
        "canonical_questions": len(canonical),
        "unique_question_ids": len(question_by_id),
        "mirror_questions": mirror_count,
        "concept_count": len({str(x.get("concept_id") or "") for x in canonical}),
        "subjects": dict(sorted(subjects.items())),
        "canonical_rows_without_provenance": without_provenance,
        "ledger_rows": len(ledger_rows),
        "review_statuses": dict(sorted(statuses.items())),
        "documented_clearances": len(cleared_ids),
        "uncleared_questions": len(question_by_id) - cleared_current,
        "unresolved_historical_ledger_entries": unresolved_historical,
        "historical_review_required": bool(ledger_rows) and retired_from_current_tree,
        "current_tree_data_boundary_passes": current_boundary_passes,
        "structural_error_count": len(problems),
        "structural_errors_preview": problems[:20],
        "human_review_required": True,
        "release_gate_passes": release_gate_passes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=CANONICAL)
    parser.add_argument("--mirror-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = audit(args.canonical, args.mirror_dir, args.ledger)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"state={report['dataset_state']} "
            f"current={report['canonical_questions']} "
            f"ledger={report['ledger_rows']} "
            f"historical_unresolved={report['unresolved_historical_ledger_entries']} "
            f"errors={report['structural_error_count']} "
            f"release_ready={report['release_gate_passes']}"
        )
    if report["structural_error_count"]:
        return 1
    if args.release_gate and not report["release_gate_passes"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
