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
# 预设学科
# ============================================================

DEFAULT_SUBJECTS: list[dict[str, Any]] = [
    {
        "id": "computer-network",
        "name": "计算机网络",
        "icon": "🌐",
        "description": "TCP/IP、HTTP、DNS、路由协议、网络安全等",
    },
    {
        "id": "data-structure",
        "name": "数据结构与算法",
        "icon": "🌳",
        "description": "链表、树、图、排序、动态规划、贪心等",
    },
    {
        "id": "operating-system",
        "name": "操作系统",
        "icon": "⚙️",
        "description": "进程管理、内存管理、文件系统、死锁等",
    },
    {
        "id": "database",
        "name": "数据库原理",
        "icon": "🗄️",
        "description": "关系模型、SQL、事务、索引、范式等",
    },
    {
        "id": "math",
        "name": "高等数学",
        "icon": "📐",
        "description": "极限、微积分、级数、微分方程等",
    },
    {
        "id": "linear-algebra",
        "name": "线性代数",
        "icon": "📊",
        "description": "矩阵、行列式、向量空间、特征值等",
    },
    {
        "id": "probability",
        "name": "概率统计",
        "icon": "🎲",
        "description": "概率论、随机变量、假设检验、回归分析等",
    },
    {
        "id": "general",
        "name": "通用知识",
        "icon": "📚",
        "description": "不限学科的通用问答",
    },
]


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
