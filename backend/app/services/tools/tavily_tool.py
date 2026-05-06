"""
Tavily 网络搜索工具
==================
通过 Tavily API 对外进行实时网络搜索，作为模型按需补充最新资料、
官网文档与权威来源的工具。

环境变量：
  TAVILY_API_KEY  — Tavily API 密钥（必需，否则工具不可用）
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

from app.shared.schemas.qa_runtime import AgentRequest

_TAVILY_API_KEY: str | None = None


def _get_tavily_client() -> Any:
    """延迟初始化 Tavily 客户端，避免启动时报错。"""
    global _TAVILY_API_KEY
    _TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip() or None
    if not _TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY 未配置，无法使用网络搜索功能。")
    try:
        from tavily import TavilyClient  # type: ignore[import]
        return TavilyClient(api_key=_TAVILY_API_KEY)
    except ImportError as exc:
        raise RuntimeError(
            "tavily-python 未安装，请在 requirements.txt 中添加 tavily-python 并重建镜像。"
        ) from exc


def tavily_available(agent_request: AgentRequest) -> bool:
    """
    只有同时满足以下条件时，Tavily 工具才对 LLM 可见：
    1. TAVILY_API_KEY 已配置
    2. guard/search_policy 允许外部搜索（由 registry 过滤）
    3. 问题类型属于可能需要知识支撑的类型
    """
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return False

    # 只在需要知识支撑的问题类型启用
    knowledge_types = {"concept", "problem", "review", "mcq_problem"}
    if agent_request.question_type not in knowledge_types:
        return False

    return True


def tavily_web_search(
    agent_request: AgentRequest,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    执行 Tavily 网络搜索，返回格式与 search_notebook_context 兼容。

    返回结构：
    {
      "query": str,
      "source": "web",
      "doc_count": int,
      "documents": [{"content": str, "metadata": {...}, "score": float}]
    }
    """
    query = str(args.get("query", "") or agent_request.question).strip()
    max_results = int(args.get("max_results", 5) or 5)
    max_results = max(1, min(max_results, 8))

    logger.info(f"🌐 Tavily 搜索开始 | query={query[:80]} | max_results={max_results}")

    try:
        client = _get_tavily_client()
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
            include_answer=True,
            include_raw_content=False,
        )
    except Exception as exc:
        logger.warning(f"⚠️ Tavily 搜索失败: {exc}")
        raise

    results = response.get("results", []) or []
    tavily_answer = response.get("answer", "") or ""

    documents: list[dict[str, Any]] = []

    # 如果 Tavily 有聚合答案，作为第一条文档
    if tavily_answer.strip():
        documents.append({
            "content": tavily_answer.strip()[:1000],
            "metadata": {
                "source": "tavily_summary",
                "url": "",
                "title": f"网络搜索摘要：{query[:40]}",
            },
            "score": 0.95,
            "distance": 0.05,
        })

    for item in results:
        content = str(item.get("content", "") or "").strip()
        if not content:
            continue
        documents.append({
            "content": content[:800],
            "metadata": {
                "source": "tavily_web",
                "url": str(item.get("url", "") or ""),
                "title": str(item.get("title", "") or ""),
            },
            "score": float(item.get("score", 0.5) or 0.5),
            "distance": 1.0 - float(item.get("score", 0.5) or 0.5),
        })

    logger.info(f"🌐 Tavily 搜索完成 | 返回 {len(documents)} 条文档")

    return {
        "query": query,
        "source": "web",
        "doc_count": len(documents),
        "documents": documents,
    }
