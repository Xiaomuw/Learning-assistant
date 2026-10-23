"""Fail if checkout left HTTP authorization headers in repository-local Git config.

Never print configuration values: an unexpected header could contain a real token.
This regression check is not a sandbox for untrusted pull-request code.
"""

from pathlib import Path
import subprocess
import sys


def check_checkout(repository: Path) -> int:
    result = subprocess.run(
        ["git", "config", "--local", "--get-regexp", r"^http(\..*)?\.extraheader$"],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print("FAIL: repository-local Git HTTP headers remain; values withheld.", file=sys.stderr)
        return 1
    if result.returncode != 1:
        print("FAIL: could not inspect repository-local Git configuration.", file=sys.stderr)
        return 1
    print("PASS: no repository-local Git HTTP headers persisted by checkout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(check_checkout(Path(__file__).resolve().parents[1]))
