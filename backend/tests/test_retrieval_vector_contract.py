from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.documents import Document

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.services.rag.retriever import diagnose_retrieval
from app.services.rag.vector_store import _build_coverage_fields, search_documents, upsert_documents
from app.shared.schemas.contracts import NotebookKnowledgeStatus, RetrievedDocument


class _FakeCollection:
    def similarity_search_with_score(self, query: str, k: int):
        return [
            (
                Document(
                    page_content="HTTP 是应用层协议。",
                    metadata={
                        "vector_id": "chapter:http:0:0",
                        "doc_type": "chapter",
                        "source_id": "auto:network",
                    },
                ),
                0.2,
            ),
            (
                Document(
                    page_content="一道数据库索引选择题。",
                    metadata={
                        "vector_id": "question_bank:q1:0",
                        "doc_type": "question_bank",
                        "source_id": "q1",
                    },
                ),
                0.7,
            ),
        ][:k]


class RetrievalVectorContractTest(unittest.TestCase):
    def test_search_documents_returns_score_and_filters_doc_types(self) -> None:
        with patch(
            "app.services.rag.vector_store.get_collection_by_name",
            return_value=_FakeCollection(),
        ):
            docs = search_documents(
                query="HTTP",
                top_k=5,
                subject_id="computer-network",
                doc_types=["chapter"],
                min_score=0.5,
            )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["doc_id"], "chapter:http:0:0")
        self.assertEqual(docs[0]["distance"], 0.2)
        self.assertEqual(docs[0]["score"], 0.8)
        self.assertEqual(docs[0]["metadata"]["doc_type"], "chapter")
        self.assertEqual(docs[0]["metadata"]["visibility"], "shared")

    def test_search_documents_merges_shared_and_personal_collections(self) -> None:
        class _SharedCollection:
            def similarity_search_with_score(self, query: str, k: int):
                return [
                    (
                        Document(
                            page_content="默认库：HTTP 默认端口是 80。",
                            metadata={"vector_id": "shared-http", "doc_type": "chapter"},
                        ),
                        0.3,
                    )
                ]

        class _PersonalCollection:
            def similarity_search_with_score(self, query: str, k: int):
                return [
                    (
                        Document(
                            page_content="我的资料：课程要求 HTTP 端口题重点记忆。",
                            metadata={"vector_id": "personal-http", "doc_type": "pdf"},
                        ),
                        0.1,
                    )
                ]

        def fake_collection(name: str):
            if "_user_" in name:
                return _PersonalCollection()
            return _SharedCollection()

        with patch("app.services.rag.vector_store.get_collection_by_name", side_effect=fake_collection):
            docs = search_documents(
                query="HTTP 端口",
                top_k=2,
                subject_id="computer-network",
                user_id="user-1",
            )

        self.assertEqual([doc["doc_id"] for doc in docs], ["personal-http", "shared-http"])
        self.assertEqual(docs[0]["metadata"]["visibility"], "personal")
        self.assertEqual(docs[0]["metadata"]["user_id"], "user-1")

    def test_upsert_documents_writes_to_target_collection_and_normalizes_subject_metadata(self) -> None:
        class _FakeEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

        with (
            patch("app.services.rag.vector_store.get_embedding_function", return_value=_FakeEmbeddings()),
            patch("app.services.rag.vector_store.delete_source_documents", return_value=0) as delete_source,
            patch("app.services.rag.vector_store.upsert_embedding_rows", return_value=1) as write_rows,
        ):
            written = upsert_documents(
                ["Example Domain\nThis page documents HTTP default port 80."],
                metadatas=[
                    {
                        "subject_id": "wrong-notebook",
                        "doc_type": "url",
                        "source": "https://example.com",
                        "source_id": "https://example.com",
                    }
                ],
                chunk_size=1000,
                chunk_overlap=0,
                subject_id="target-notebook",
            )

        self.assertEqual(written, 1)
        delete_source.assert_called_once_with(
            subject_id="target-notebook",
            source_id="https://example.com",
            doc_type="url",
            user_id=None,
        )
        collection_name, rows = write_rows.call_args.args
        self.assertEqual(collection_name, "learning_target-notebook")
        self.assertEqual(rows[0]["custom_id"], "url:https://example.com:0:0")
        self.assertEqual(rows[0]["metadata"]["subject_id"], "target-notebook")
        self.assertEqual(rows[0]["metadata"]["doc_type"], "url")
        self.assertEqual(rows[0]["metadata"]["source_id"], "https://example.com")

    def test_knowledge_coverage_fields_classify_empty_sparse_and_ready(self) -> None:
        empty = _build_coverage_fields(
            doc_count=0,
            chapter_count=0,
            exam_pattern_count=0,
            question_count=0,
            url_count=0,
            pdf_count=0,
            embedding_ready=False,
        )
        self.assertEqual(empty["coverage_level"], "empty")
        self.assertFalse(empty["retrieval_ready"])
        self.assertIn("chapter", empty["missing_doc_types"])

        sparse = _build_coverage_fields(
            doc_count=4,
            chapter_count=4,
            exam_pattern_count=0,
            question_count=0,
            url_count=0,
            pdf_count=0,
            embedding_ready=True,
        )
        self.assertEqual(sparse["coverage_level"], "sparse")
        self.assertTrue(sparse["retrieval_ready"])
        self.assertIn("question_bank", sparse["missing_doc_types"])

        ready = _build_coverage_fields(
            doc_count=32,
            chapter_count=10,
            exam_pattern_count=4,
            question_count=8,
            url_count=6,
            pdf_count=8,
            embedding_ready=True,
        )
        self.assertEqual(ready["coverage_level"], "ready")
        self.assertTrue(ready["retrieval_ready"])

    def test_retrieval_diagnostics_distinguish_low_score(self) -> None:
        with patch(
            "app.services.rag.retriever.get_collection_document_status",
            return_value=NotebookKnowledgeStatus(
                subject_id="network",
                collection_name="learning_network",
                doc_count=3,
                chapter_count=3,
                embedding_ready=True,
                coverage_score=35,
                coverage_level="sparse",
                retrieval_ready=True,
            ),
        ):
            diagnostics = diagnose_retrieval(
                query="HTTP 端口",
                docs=[
                    RetrievedDocument(
                        doc_id="chapter:http:0:0",
                        content="HTTP 是应用层协议。",
                        metadata={"doc_type": "chapter"},
                        score=0.2,
                        distance=0.8,
                    )
                ],
                subject_id="network",
                min_ready_score=0.5,
            )

        self.assertEqual(diagnostics.diagnosis, "low_score")
        self.assertEqual(diagnostics.hit_count, 1)
        self.assertEqual(diagnostics.doc_type_counts["chapter"], 1)


if __name__ == "__main__":
    unittest.main()
