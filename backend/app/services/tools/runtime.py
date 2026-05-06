"""Q&A tool runtime façade.

新增代码优先从 args / definitions / internal_tools / mcp_tools / registry
这些明确模块导入。本文件保留为主问答 runtime 的稳定聚合入口。
"""

from __future__ import annotations

from app.services.tools.args import (  # noqa: F401
    LearningProfileArgs,
    MCPWebReadArgs,
    MCPWebSearchArgs,
    NotebookSearchArgs,
    RecommendQuestionsArgs,
    SessionSummaryArgs,
)
from app.services.tools.definitions import ToolDefinition  # noqa: F401
from app.services.tools.mcp_tools import call_mcp_tool, is_tool_available  # noqa: F401
from app.services.tools.registry import (  # noqa: F401
    ToolExecutor,
    ToolRegistry,
    tool_executor,
    tool_registry,
)
