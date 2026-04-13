"""
Chroma 向量检索工具
===================
职责：
  1. 管理 Chroma 客户端和 Collection 的生命周期
  2. 提供文档入库接口（PDF 分块后写入）
  3. 提供相似度检索接口
  4. 对检索结果进行相关性打分 & 过滤
"""

from __future__ import annotations

import os
from typing import Any

import chromadb
from chromadb.config import Settings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from tools.model_provider import get_embeddings


# ============================================================
# Chroma 客户端单例
# ============================================================

_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    """获取 / 初始化 Chroma 客户端（自动检测 Docker 环境）"""
    global _client
    if _client is None:
        chroma_host = os.getenv("CHROMA_HOST")
        if chroma_host:
            # Docker 环境：连接远程 Chroma 容器
            chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
            _client = chromadb.HttpClient(
                host=chroma_host,
                port=chroma_port,
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info(f"✅ Chroma HttpClient 已连接: {chroma_host}:{chroma_port}")
        else:
            # 本地开发：使用持久化文件
            persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
            _client = chromadb.PersistentClient(
                path=persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info(f"✅ Chroma PersistentClient 已初始化: {persist_dir}")
    return _client


def get_collection(subject_id: str | None = None) -> chromadb.Collection:
    """获取 / 创建 Collection（按学科路由）"""
    global _collection
    if subject_id:
        # 按学科获取独立 Collection
        client = get_chroma_client()
        collection_name = f"learning_{subject_id}"
        col = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"✅ Collection '{collection_name}' 已就绪")
        return col

    # 默认 Collection（兼容旧逻辑）
    if _collection is None:
        client = get_chroma_client()
        collection_name = os.getenv("CHROMA_COLLECTION_NAME", "learning_docs")
        _collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"✅ Collection '{collection_name}' 已就绪")
    return _collection


# ============================================================
# Embedding 工具
# ============================================================

def get_embedding_function():
    """返回 OpenAI Embedding 模型实例"""
    return get_embeddings(default_model="text-embedding-3-small")


# ============================================================
# 文档入库
# ============================================================

def ingest_documents(
    texts: list[str],
    metadatas: list[dict[str, Any]] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    subject_id: str | None = None,
) -> int:
    """
    将文本列表分块后写入 Chroma。

    Args:
        texts: 原始文本列表（例如每页 PDF 的文本）
        metadatas: 每段文本对应的元信息
        chunk_size: 分块大小，默认从环境变量读取
        chunk_overlap: 分块重叠，默认从环境变量读取

    Returns:
        写入的分块总数
    """
    _chunk_size = chunk_size or int(os.getenv("CHUNK_SIZE", "1000"))
    _chunk_overlap = chunk_overlap or int(os.getenv("CHUNK_OVERLAP", "200"))

    # ---- 文本分块 ----
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_chunk_size,
        chunk_overlap=_chunk_overlap,
        length_function=len,
    )

    all_chunks: list[str] = []
    all_metas: list[dict[str, Any]] = []

    for i, text in enumerate(texts):
        chunks = splitter.split_text(text)
        meta = (metadatas[i] if metadatas and i < len(metadatas) else {})
        for j, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_metas.append({**meta, "chunk_index": j})

    if not all_chunks:
        logger.warning("⚠️ 分块结果为空，无内容可入库")
        return 0

    # ---- 生成唯一 ID ----
    import uuid
    ids = [str(uuid.uuid4()) for _ in all_chunks]

    # ---- 写入 Chroma（使用内置 embedding） ----
    collection = get_collection(subject_id=subject_id)

    # Chroma 单次 add 上限较大，但分批更安全
    batch_size = 100
    for start in range(0, len(all_chunks), batch_size):
        end = min(start + batch_size, len(all_chunks))
        collection.add(
            ids=ids[start:end],
            documents=all_chunks[start:end],
            metadatas=all_metas[start:end],
        )

    logger.info(f"✅ 入库完成: {len(texts)} 段原文 → {len(all_chunks)} 个分块")
    return len(all_chunks)


# ============================================================
# 相似度检索
# ============================================================

def retrieve(
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    对用户问题执行向量检索。

    Args:
        query: 用户问题文本
        top_k: 返回 Top-K 条结果

    Returns:
        检索结果列表，每个元素:
        {
            "content": str,
            "metadata": dict,
            "score": float,        # 相似度得分 (0~1, 越高越相关)
        }
    """
    # ---- 检查 collection 是否有数据 ----
    collection = get_collection()
    if collection.count() == 0:
        logger.warning("⚠️ Collection 为空，无文档可检索")
        return []

    # ---- Embedding query ----
    embed_fn = get_embedding_function()
    query_embedding = embed_fn.embed_query(query)

    # ---- Chroma 检索 ----
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    # ---- 组装统一格式 ----
    docs: list[dict[str, Any]] = []
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for content, meta, dist in zip(documents, metadatas, distances):
        # Chroma cosine distance ∈ [0, 2]，转换为相似度 ∈ [0, 1]
        similarity = max(0.0, 1.0 - dist)
        docs.append({
            "content": content,
            "metadata": meta or {},
            "score": round(similarity, 4),
        })

    logger.info(f"🔍 检索完成: query='{query[:50]}…', 召回 {len(docs)} 篇")
    return docs


# ============================================================
# 文档打分 & 过滤
# ============================================================

def score_and_filter(
    docs: list[dict[str, Any]],
    threshold: float = 0.65,
) -> list[dict[str, Any]]:
    """
    对检索结果进行相关性打分，过滤掉低于阈值的文档。

    Args:
        docs: retrieve() 返回的原始文档列表
        threshold: 相关性阈值，低于此值的文档将被丢弃

    Returns:
        过滤后的文档列表（按 score 降序排列）
    """
    if not docs:
        return []

    # ---- 按 threshold 过滤 ----
    filtered = [d for d in docs if d.get("score", 0) >= threshold]
    removed = len(docs) - len(filtered)

    # ---- 按 score 降序排序 ----
    filtered.sort(key=lambda d: d.get("score", 0), reverse=True)

    if removed:
        logger.info(f"🗑️ 过滤掉 {removed} 篇低分文档 (score < {threshold})")
    logger.info(f"📊 过滤后保留 {len(filtered)} 篇文档")

    return filtered
