#!/usr/bin/env python3
"""Run all backend unittest modules in isolated Python interpreters.

The aggregator tests/test_agent_graphs.py imports the same graph modules tested
individually; it is intentionally omitted to avoid duplicate execution.
Each other test_*.py module runs exactly once. Any nonzero exit makes CI fail.
An isolated PostgreSQL database is required by the CI workflow, and this
script never provisions or deletes databases itself.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
TESTS_ROOT = BACKEND_ROOT / "tests"
AGGREGATOR_MODULES = {"test_agent_graphs.py"}


def main() -> int:
    modules = sorted(
        path.stem for path in TESTS_ROOT.glob("test_*.py")
        if path.name not in AGGREGATOR_MODULES
    )
    if len(modules) < 60:
        print(f"Refusing suspiciously incomplete test suite: {len(modules)} modules", flush=True)
        return 2
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPOSITORY_ROOT), str(BACKEND_ROOT), env.get("PYTHONPATH", "")) if part
    )
    failed: list[str] = []
    print(f"Running {len(modules)} standalone backend test modules.", flush=True)
    for index, module in enumerate(modules, 1):
        print(f"\n[{index}/{len(modules)}] tests.{module}", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "-v", f"tests.{module}"],
            cwd=BACKEND_ROOT,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            failed.append(module)
    print(
        f"\nModules: {len(modules)} | passed: {len(modules) - len(failed)}"
        f" | failed: {len(failed)}",
        flush=True,
    )
    if failed:
        print("Failing modules: " + ", ".join(failed), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
