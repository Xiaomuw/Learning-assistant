"""
Explicit app data bootstrap.

默认只做 dry-run。真实写入必须显式传入：
  python scripts/bootstrap_app_data.py --confirm BOOTSTRAP_APP_DATA
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.infrastructure.db.repositories.bootstrap import (  # noqa: E402
    BOOTSTRAP_APP_DATA_CONFIRM_TOKEN,
    bootstrap_app_data,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="显式 bootstrap 默认学科、应用配置、taxonomy 与 legacy 数据")
    parser.add_argument(
        "--confirm",
        default="",
        help=f"传入 {BOOTSTRAP_APP_DATA_CONFIRM_TOKEN} 才会真实写入；默认 dry-run",
    )
    args = parser.parse_args(argv)

    report = bootstrap_app_data(confirm=args.confirm)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
