"""
Fail-open MCP runtime probe.

启动脚本调用它来提前打印 MCP tools/list 诊断。失败不会阻塞服务启动。
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.infrastructure.mcp import initialize_mcp  # noqa: E402


def main() -> int:
    initialize_mcp()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
