from __future__ import annotations

from pydantic import BaseModel, Field


class NotebookSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=4, ge=1, le=6)


class SessionSummaryArgs(BaseModel):
    include_open_loops: bool = Field(default=True)


class LearningProfileArgs(BaseModel):
    focus: str = Field(default="overview", max_length=120)


class RecommendQuestionsArgs(BaseModel):
    topic: str = Field(default="", max_length=120)
    limit: int = Field(default=3, ge=1, le=5)


class MCPWebSearchArgs(BaseModel):
    query: str = Field(default="", max_length=220)
    max_results: int = Field(default=3, ge=1, le=5)


class MCPWebReadArgs(BaseModel):
    url: str = Field(min_length=8, max_length=500)


class TavilySearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=400, description="搜索查询词，尽量具体精准")
    max_results: int = Field(default=5, ge=1, le=8, description="最多返回条数")
