"""
检查当前 backend/.env 是否符合正式运行时要求。

用法:
  python scripts/check_environment.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.config.validation import (  # noqa: E402
    EnvironmentValidationError,
    collect_environment_warnings,
    validate_startup_environment,
)


def main() -> int:
    load_dotenv(dotenv_path=BACKEND_ROOT / ".env")

    try:
        validate_startup_environment()
    except EnvironmentValidationError as exc:
        print(f"❌ 环境检查失败: {exc}")
        return 1

    print("✅ 启动级环境检查通过")
    for warning in collect_environment_warnings():
        print(f"⚠️  {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
