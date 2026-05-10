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

from app.services.rag.retriever import DEFAULT_RELEVANCE_THRESHOLD, diagnose_retrieval
from app.services.rag.vector_store import (
    _build_coverage_fields,
    _build_vector_id,
    _keyword_score,
    _validate_embedding_dimensions,
    get_collection_document_status,
    search_documents,
    upsert_documents,
)
from app.shared.schemas.contracts import NotebookKnowledgeStatus, RetrievedDocument


class _FakeCollection:
    def similarity_search_with_score(self, query: str, k: int, filter=None):
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

    def test_search_documents_rejects_missing_doc_type_when_doc_types_are_requested(self) -> None:
        class _MixedCollection:
            def similarity_search_with_score(self, query: str, k: int, filter=None):
                return [
                    (
                        Document(
                            page_content="旧数据缺少 doc_type。",
                            metadata={"vector_id": "legacy-1"},
                        ),
                        0.1,
                    ),
                    (
                        Document(
                            page_content="HTTP 是应用层协议。",
                            metadata={"vector_id": "chapter-http", "doc_type": "chapter"},
                        ),
                        0.2,
                    ),
                ][:k]

        with patch(
            "app.services.rag.vector_store.get_collection_by_name",
            return_value=_MixedCollection(),
        ):
            docs = search_documents(
                query="HTTP",
                top_k=5,
                subject_id="computer-network",
                doc_types=["chapter"],
            )

        self.assertEqual([doc["doc_id"] for doc in docs], ["chapter-http"])

    def test_search_documents_relaxes_concept_filter_to_topic_filter(self) -> None:
        class _ConceptAwareCollection:
            def similarity_search_with_score(self, query: str, k: int, filter=None):
                if "concept_id" in repr(filter):
                    return []
                return [
                    (
                        Document(
                            page_content="二叉树遍历包含前序、中序、后序。",
                            metadata={
                                "vector_id": "topic-binary-tree",
                                "doc_type": "chapter",
                                "topic_id": "ds.binary-tree",
                            },
                        ),
                        0.15,
                    )
                ]

        with patch(
            "app.services.rag.vector_store.get_collection_by_name",
            return_value=_ConceptAwareCollection(),
        ):
            docs = search_documents(
                query="二叉树遍历",
                top_k=5,
                subject_id="data-structures",
                doc_types=["chapter"],
                metadata_filter={
                    "concept_id": "ds_binary_tree_traversal",
                    "topic_id": "ds.binary-tree",
                },
            )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["metadata"]["retrieval_stage"], "relaxed_topic")

    def test_search_documents_merges_shared_and_personal_collections(self) -> None:
        class _SharedCollection:
            def similarity_search_with_score(self, query: str, k: int, filter=None):
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
            def similarity_search_with_score(self, query: str, k: int, filter=None):
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

    def test_question_bank_vector_id_is_stable_and_bounded(self) -> None:
        long_source_id = "https://example.com/" + "binary-tree/" * 20 + "question-001"
        single = _build_vector_id("question_bank", long_source_id, 1, 0, 0)
        batch = _build_vector_id("question_bank", long_source_id, 5, 3, 0)

        self.assertEqual(single, batch)
        self.assertLessEqual(len(single), 120)
        self.assertTrue(single.startswith("question_bank:"))

    def test_keyword_single_hit_clears_default_relevance_threshold(self) -> None:
        self.assertGreaterEqual(_keyword_score("HTTP 是应用层协议。", ["http"]), DEFAULT_RELEVANCE_THRESHOLD)

    def test_embedding_dimension_mismatch_fails_before_write(self) -> None:
        with patch.dict(os.environ, {"PGVECTOR_EMBEDDING_DIMENSION": "3"}, clear=False):
            with self.assertRaises(ValueError):
                _validate_embedding_dimensions(
                    [
                        {
                            "embedding": [0.1, 0.2],
                            "document": "维度不匹配",
                            "metadata": {},
                        }
                    ]
                )

    def test_upsert_documents_writes_to_target_collection_and_normalizes_subject_metadata(self) -> None:
        class _FakeEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

        with (
            patch("app.services.rag.vector_store.get_embedding_function", return_value=_FakeEmbeddings()),
            patch("app.services.rag.vector_store.delete_source_documents", return_value=0) as delete_source,
            patch("app.services.rag.vector_store.save_kb_chunk_record"),
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
        self.assertEqual(rows[0]["custom_id"], "url:https_example.com:0:0")
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
        self.assertFalse(empty["content_ready"])
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
        self.assertTrue(sparse["content_ready"])
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

        blocked = _build_coverage_fields(
            doc_count=4,
            chapter_count=4,
            exam_pattern_count=0,
            question_count=0,
            url_count=0,
            pdf_count=0,
            embedding_ready=True,
            index_ready=False,
        )
        self.assertTrue(blocked["content_ready"])
        self.assertFalse(blocked["retrieval_ready"])

    def test_collection_status_separates_pgvector_model_content_and_retrieval_readiness(self) -> None:
        counts = {
            "doc_count": 4,
            "chapter_count": 4,
            "exam_pattern_count": 0,
            "question_count": 0,
            "url_count": 0,
            "pdf_count": 0,
        }
        with (
            patch(
                "app.services.rag.vector_store.describe_vector_store_health",
                return_value={
                    "pgvector_ready": True,
                    "schema_ready": True,
                    "index_ready": True,
                    "embedding_model_ready": False,
                    "embedding_model_error": "embedding_api_key_missing",
                    "schema_issues": [],
                    "embedding_profile": {"embedding_model": "models/gemini-embedding-2"},
                },
            ),
            patch("app.services.rag.vector_store._get_collection_counts", return_value=counts),
        ):
            status = get_collection_document_status(subject_id="network")

        self.assertTrue(status.pgvector_ready)
        self.assertTrue(status.schema_ready)
        self.assertTrue(status.index_ready)
        self.assertFalse(status.embedding_model_ready)
        self.assertFalse(status.embedding_ready)
        self.assertTrue(status.content_ready)
        self.assertFalse(status.retrieval_ready)
        self.assertEqual(status.embedding_model_error, "embedding_api_key_missing")

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

    def test_retrieval_diagnostics_preserve_low_score_raw_hits_after_filtering(self) -> None:
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
                docs=[],
                raw_docs=[
                    RetrievedDocument(
                        doc_id="chapter:http:0:0",
                        content="HTTP 是应用层协议。",
                        metadata={"doc_type": "chapter", "retrieval_stage": "strict"},
                        score=0.2,
                        distance=0.8,
                    )
                ],
                subject_id="network",
                min_ready_score=0.5,
                filter_reason="all_below_score_threshold",
            )

        self.assertEqual(diagnostics.diagnosis, "low_score")
        self.assertEqual(diagnostics.hit_count, 0)
        self.assertEqual(diagnostics.raw_hit_count, 1)
        self.assertEqual(diagnostics.raw_top_score, 0.2)
        self.assertEqual(diagnostics.filter_reason, "all_below_score_threshold")


if __name__ == "__main__":
    unittest.main()
