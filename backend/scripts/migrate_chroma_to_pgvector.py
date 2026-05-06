from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _normalize_target_database_url(raw_url: str) -> str:
    normalized = raw_url.strip()
    if normalized.startswith("postgres://"):
        return normalized.replace("postgres://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgresql+psycopg://"):
        return normalized
    raise RuntimeError("target-url 必须是 PostgreSQL DSN。")


def _configure_target_env(target_url: str) -> None:
    normalized = _normalize_target_database_url(target_url)
    os.environ["DATABASE_URL"] = normalized
    os.environ.setdefault(
        "LANGGRAPH_POSTGRES_URL",
        normalized.replace("postgresql+psycopg://", "postgresql://", 1),
    )


def _load_target_modules():
    for module_name in [
        "app.services.rag.vector_store",
        "app.infrastructure.db.repositories.bootstrap",
        "app.infrastructure.db.models",
        "app.infrastructure.db.database",
    ]:
        sys.modules.pop(module_name, None)

    db_database = importlib.import_module("app.infrastructure.db.database")
    db_bootstrap = importlib.import_module("app.infrastructure.db.repositories.bootstrap")
    retrieval_store = importlib.import_module("app.services.rag.vector_store")
    return db_database, db_bootstrap, retrieval_store


def _load_chroma_client(args):
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as exc:
        raise RuntimeError(
            "未安装 chromadb。请先执行 `pip install -r backend/requirements-migration.txt`。"
        ) from exc

    if args.chroma_path:
        return chromadb.PersistentClient(
            path=args.chroma_path,
            settings=Settings(anonymized_telemetry=False),
        )

    if not args.chroma_host:
        raise RuntimeError("请提供 --chroma-path 或 --chroma-host。")

    return chromadb.HttpClient(
        host=args.chroma_host,
        port=args.chroma_port,
        settings=Settings(anonymized_telemetry=False),
    )


def _iter_collection_names(client) -> list[str]:
    raw = client.list_collections()
    names: list[str] = []
    for item in raw:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = str(item.get("name", "") or "").strip()
            if name:
                names.append(name)
        else:
            name = str(getattr(item, "name", "") or "").strip()
            if name:
                names.append(name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="将 Chroma 向量集合迁移到 PGVector。")
    parser.add_argument("--target-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--chroma-path", help="本地 Chroma PersistentClient 目录。")
    parser.add_argument("--chroma-host", help="远程 Chroma 主机名。")
    parser.add_argument("--chroma-port", type=int, default=8000, help="远程 Chroma 端口。")
    parser.add_argument("--collection", help="仅迁移单个 collection。")
    args = parser.parse_args()

    if not args.target_url:
        raise RuntimeError("请通过 --target-url 或环境变量 DATABASE_URL 指定目标 PostgreSQL DSN。")

    client = _load_chroma_client(args)
    _configure_target_env(args.target_url)
    db_database, db_repositories, retrieval_store = _load_target_modules()
    db_database.ensure_postgres_extensions()
    db_repositories.init_database()

    collection_names = [args.collection] if args.collection else _iter_collection_names(client)
    report: dict[str, dict[str, int]] = {}

    for collection_name in collection_names:
        collection = client.get_collection(collection_name)
        payload = collection.get(include=["documents", "metadatas", "embeddings"])

        ids = list(payload.get("ids") or [])
        documents = list(payload.get("documents") or [])
        metadatas = list(payload.get("metadatas") or [])
        embeddings = list(payload.get("embeddings") or [])

        direct_rows: list[dict[str, Any]] = []
        fallback_documents: list[Document] = []
        fallback_ids: list[str] = []

        for index, custom_id in enumerate(ids):
            document = str(documents[index] or "") if index < len(documents) else ""
            metadata = dict(metadatas[index] or {}) if index < len(metadatas) else {}
            metadata.setdefault("vector_id", custom_id)

            embedding = embeddings[index] if index < len(embeddings) else None
            if embedding and document:
                direct_rows.append(
                    {
                        "custom_id": custom_id,
                        "embedding": embedding,
                        "document": document,
                        "metadata": metadata,
                    }
                )
                continue

            if document:
                fallback_documents.append(Document(page_content=document, metadata=metadata))
                fallback_ids.append(custom_id)

        direct_written = retrieval_store.upsert_embedding_rows(collection_name, direct_rows)
        fallback_written = 0
        if fallback_documents:
            store = retrieval_store.ensure_collection_ready(collection_name)
            store.add_documents(documents=fallback_documents, ids=fallback_ids)
            fallback_written = len(fallback_documents)

        report[collection_name] = {
            "total": len(ids),
            "direct_copied": direct_written,
            "reembedded": fallback_written,
        }

    print("Vector migration completed:")
    for collection_name, stats in report.items():
        print(
            f"- {collection_name}: total={stats['total']}, "
            f"direct_copied={stats['direct_copied']}, reembedded={stats['reembedded']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
