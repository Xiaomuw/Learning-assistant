"""
学科数据模型
============
定义学科的数据结构和预设学科列表。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# Pydantic 模型
# ============================================================

class SubjectCreate(BaseModel):
    """创建学科请求体"""
    name: str = Field(..., min_length=1, max_length=100, description="学科名称")
    icon: str = Field(default="📚", max_length=10, description="学科图标 emoji")
    description: str = Field(default="", max_length=500, description="学科简介")


class SubjectUpdate(BaseModel):
    """更新学科 / 笔记本请求体"""
    name: str = Field(..., min_length=1, max_length=100, description="学科名称")
    icon: str = Field(default="📚", max_length=10, description="学科图标 emoji")
    description: str = Field(default="", max_length=500, description="学科简介")


class SubjectInfo(BaseModel):
    """学科完整信息"""
    id: str
    name: str
    icon: str
    description: str
    doc_count: int = 0
    created_at: str = ""


# ============================================================
# 预设知识库
# ============================================================

CANONICAL_SUBJECT_IDS: tuple[str, ...] = (
    "data-structure",
    "computer-network",
    "computer-organization",
    "operating-system",
)
DEFAULT_SUBJECT_ID = CANONICAL_SUBJECT_IDS[0]

DEFAULT_SUBJECTS: list[dict[str, Any]] = [
    {
        "id": "data-structure",
        "name": "数据结构与算法",
        "icon": "🌳",
        "description": "线性表、树、图、排序、查找、动态规划、贪心等",
    },
    {
        "id": "computer-network",
        "name": "计算机网络",
        "icon": "🌐",
        "description": "TCP/IP、HTTP、DNS、路由协议、网络安全等",
    },
    {
        "id": "computer-organization",
        "name": "计算机组成原理",
        "icon": "🧠",
        "description": "数据表示、存储系统、指令系统、CPU、总线与 I/O 等",
    },
    {
        "id": "operating-system",
        "name": "操作系统原理",
        "icon": "⚙️",
        "description": "进程管理、内存管理、文件系统、I/O、死锁等",
    },
]


def is_canonical_subject_id(subject_id: str | None) -> bool:
    """判断是否为当前产品可见的四个固定知识库之一。"""
    return str(subject_id or "").strip() in CANONICAL_SUBJECT_IDS


def normalize_subject_id(subject_id: str | None) -> str:
    """将旧 general/隐藏知识库/空值归一到默认固定知识库。"""
    normalized = str(subject_id or "").strip()
    if normalized in CANONICAL_SUBJECT_IDS:
        return normalized
    return DEFAULT_SUBJECT_ID


def slugify(name: str) -> str:
    """将中文名称转换为 URL 友好的 slug"""
    import hashlib
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = ascii_name.lower().strip().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")

    if len(slug) < 3:
        slug = f"subject-{hashlib.md5(name.encode('utf-8')).hexdigest()[:8]}"

    return slug[:63].strip("-")
