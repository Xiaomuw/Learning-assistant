"""Real URL parsing, splitting, PGVector and citations; deterministic embeddings.

Run in the isolated unittest runner. Only a loopback *_test PostgreSQL service
with CREATEDB and the vector extension installed is accepted. No model API runs.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from sqlalchemy import select, text

from tests.postgres_test_utils import TemporaryPostgresDatabase

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class ControlledEmbeddings(Embeddings):
    """A deliberately non-semantic vector fixture; never claims model quality."""
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] if "cobalt" in value else [0.0, 1.0, 0.0] for value in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class RagIngestionPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database = cls.enterClassContext(TemporaryPostgresDatabase())
        cls.enterClassContext(patch.dict(os.environ, {
            "DATABASE_URL": cls.database.database_url,
            "ALEMBIC_DATABASE_URL": cls.database.database_url,
            "LANGGRAPH_POSTGRES_URL": cls.database.database_url.replace("postgresql+psycopg://", "postgresql://", 1),
            "PGVECTOR_EMBEDDING_DIMENSION": "3", "PGVECTOR_DISTANCE_STRATEGY": "cosine",
            "CHUNK_SIZE": "120", "CHUNK_OVERLAP": "20",
        }))
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_ROOT, check=True, timeout=120)
        # Import only after selecting our own database; the suite uses one process per module.
        cls.db = importlib.import_module("app.infrastructure.db.database")
        cls.addClassCleanup(cls.db.engine.dispose)
        with cls.db.engine.connect() as connection:
            actual = connection.execute(text("SELECT current_database()")).scalar_one()
            if actual != cls.database.name:
                raise AssertionError("Application engine escaped the disposable database")
        cls.models = importlib.import_module("app.infrastructure.db.models")
        subjects = importlib.import_module("app.infrastructure.db.repositories.subjects")
        cls.subject = subjects.create_subject_record("computer-network").id
        cls.store = importlib.import_module("app.services.rag.vector_store")
        profile = importlib.import_module("app.services.rag.embedding_profile").EmbeddingProfile(
            provider="synthetic-test", model_id="controlled-three-dimensions", dimension=3,
        )
        cls.enterClassContext(patch.object(cls.store, "get_embedding_function", return_value=ControlledEmbeddings()))
        cls.enterClassContext(patch.object(cls.store, "get_embedding_profile", return_value=profile))
        cls.addClassCleanup(cls.close_vector_pools)

    @classmethod
    def close_vector_pools(cls) -> None:
        for store in cls.store._store_cache.values():
            store._engine.dispose()
        cls.store._store_cache.clear()

    def setUp(self) -> None:
        self.lesson = "cobalt HTTP requests contain a method, a target and optional content. " * 6
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                content = ("<html><nav>excluded navigation</nav><main>" + owner.lesson + "</main></html>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = f"http://127.0.0.1:{self.server.server_port}/original-lesson"
        upload = importlib.import_module("app.interfaces.api.upload")
        auth = importlib.import_module("app.interfaces.auth.dependencies")
        app = FastAPI()
        app.include_router(upload.router, prefix="/api")
        self.user = "synthetic-alice"
        app.dependency_overrides[auth.require_current_user] = lambda: SimpleNamespace(id=self.user)
        self.client = self.enterContext(TestClient(app))

    def close_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())

    def ingest(self) -> dict:
        response = self.client.post("/api/upload/urls", json={"subject_id": self.subject, "urls": [self.url]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def mappings(self) -> list:
        with self.db.session_scope() as session:
            return list(session.scalars(select(self.models.KbChunkModel).where(
                self.models.KbChunkModel.source_file == self.url,
            )))

    def retrieve(self, user: str | None) -> list[dict]:
        # No lexical overlap: keyword fallback must not masquerade as vector retrieval.
        with patch.object(self.store, "_keyword_search_documents", side_effect=AssertionError("unexpected keyword fallback")) as fallback:
            docs = self.store.search_documents(
                "vector probe", subject_id=self.subject, user_id=user,
                doc_types=["url"], metadata_filter={"source_id": self.url}, min_score=0.95,
            )
            fallback.assert_not_called()
        return docs

    def test_import_split_vector_retrieve_citations_and_reimport(self) -> None:
        first = self.ingest()
        self.assertGreater(first["total_chunks"], 1)
        self.assertEqual(first["successful_urls"], 1)
        rows = self.mappings()
        self.assertEqual(len(rows), first["total_chunks"])
        self.assertTrue(all("excluded navigation" not in row.content_text for row in rows))
        docs = self.retrieve(self.user)
        self.assertTrue(docs, "Real vector retrieval must produce evidence")
        for doc in docs:
            self.assertEqual(doc["score"], 1.0)
            self.assertIn("cobalt", doc["content"])
            self.assertIn(doc["content"], self.lesson)
            self.assertEqual(doc["metadata"]["source"], self.url)
            self.assertEqual(doc["metadata"]["source_file"], self.url)
            self.assertEqual(doc["metadata"]["user_id"], self.user)
            self.assertEqual(doc["metadata"]["visibility"], "personal")
            self.assertEqual(doc["metadata"]["filter_mode"], "pgvector")
            self.assertIn(doc["doc_id"], {row.vector_id for row in rows})
        second = self.ingest()
        self.assertEqual(second["total_chunks"], first["total_chunks"])
        self.assertEqual({row.id for row in self.mappings()}, {row.id for row in rows})
        self.assertEqual(self.store.count_collection_documents(self.subject, self.user), first["total_chunks"])

    def test_same_source_for_two_users_keeps_both_mappings_and_private_vectors(self) -> None:
        first = self.ingest()
        self.user = "synthetic-bob"
        self.lesson = self.lesson.replace("cobalt", "amber")
        second = self.ingest()
        rows = self.mappings()
        self.assertEqual(len(rows), first["total_chunks"] + second["total_chunks"])
        self.assertEqual({row.metadata_json["user_id"] for row in rows}, {"synthetic-alice", "synthetic-bob"})
        alice = self.retrieve("synthetic-alice")
        self.assertTrue(alice)
        self.assertTrue(all("amber" not in doc["content"] for doc in alice))
        # Direct real vector query avoids the intentionally allowed empty-result keyword fallback.
        for user in ("synthetic-bob", "synthetic-outsider"):
            docs = self.store._search_collection_documents(
                collection_name=self.store.resolve_personal_collection_name(self.subject, user),
                query="vector probe", top_k=10, doc_types=["url"],
                metadata_filter={"source_id": self.url}, min_score=0.95,
                visibility="personal", user_id=user,
            )
            self.assertEqual(docs, [])


if __name__ == "__main__":
    unittest.main()
