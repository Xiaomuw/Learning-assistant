from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.services.rag.vector_store import _record_kb_chunk_mapping, upsert_documents, upsert_documents_with_summary  # noqa: E402


class IngestTaxonomyMappingTest(unittest.TestCase):
    def test_mapping_identity_is_stable_bounded_and_scoped_to_owner_and_subject(self) -> None:
        identities = []
        for subject, user in [("computer-network", "alice"), ("computer-network", "bob"),
                              ("computer-network", None), ("data-structure", "alice"),
                              ("computer-network", "alice")]:
            with patch("app.services.rag.vector_store.save_kb_chunk_record") as save:
                _record_kb_chunk_mapping(
                    vector_id="pdf:synthetic.pdf:0:0",
                    metadata={"subject_id": subject, "user_id": user}, content="Original synthetic text",
                )
            payload = save.call_args.args[0]
            self.assertEqual(payload["vector_id"], "pdf:synthetic.pdf:0:0")
            self.assertLessEqual(len(payload["id"]), 120)
            identities.append(payload["id"])
        self.assertEqual(len(set(identities[:4])), 4)
        self.assertEqual(identities[0], identities[-1])

    def test_mapped_chunk_gets_concept_metadata_and_enters_vector_store(self) -> None:
        class _FakeEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

        with (
            patch("app.services.rag.vector_store.get_embedding_function", return_value=_FakeEmbeddings()),
            patch("app.services.rag.vector_store.delete_source_documents", return_value=0),
            patch("app.services.rag.vector_store.delete_kb_chunks_by_source", return_value=0) as delete_chunks,
            patch("app.services.rag.vector_store.save_kb_chunk_record") as save_chunk,
            patch("app.services.rag.vector_store.upsert_embedding_rows", return_value=1) as write_rows,
        ):
            written = upsert_documents(
                ["HTTP 默认端口是 80，HTTPS 默认端口是 443。"],
                metadatas=[
                    {
                        "subject_id": "computer-network",
                        "doc_type": "pdf",
                        "source": "network.pdf",
                        "source_id": "network.pdf",
                        "page": 3,
                    }
                ],
                chunk_size=1000,
                chunk_overlap=0,
                subject_id="computer-network",
                user_id="user-1",
            )

        self.assertEqual(written, 1)
        delete_chunks.assert_called_once_with(
            subject_id="computer-network",
            source_file="network.pdf",
            source_id="network.pdf",
            doc_type="pdf",
            user_id="user-1",
        )
        metadata = write_rows.call_args.args[1][0]["metadata"]
        self.assertEqual(metadata["mapping_status"], "mapped")
        self.assertEqual(metadata["concept_id"], "computer-network.application.http-https")
        self.assertEqual(metadata["subject_id"], "computer-network")
        self.assertEqual(metadata["page_start"], 3)
        saved_payload = save_chunk.call_args.args[0]
        self.assertEqual(saved_payload["mapping_status"], "mapped")

    def test_unmapped_chunk_is_recorded_and_written_to_vector_store(self) -> None:
        class _FakeEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

        with (
            patch("app.services.rag.vector_store.get_embedding_function", return_value=_FakeEmbeddings()),
            patch("app.services.rag.vector_store.delete_source_documents", return_value=0),
            patch("app.services.rag.vector_store.delete_kb_chunks_by_source", return_value=0),
            patch("app.services.rag.vector_store.save_kb_chunk_record") as save_chunk,
            patch("app.services.rag.vector_store.upsert_embedding_rows", return_value=1) as write_rows,
        ):
            written = upsert_documents(
                ["这段文本只讨论番茄的颜色和厨房收纳，没有任何课程知识点。"],
                metadatas=[
                    {
                        "subject_id": "computer-network",
                        "doc_type": "pdf",
                        "source": "unknown.pdf",
                        "source_id": "unknown.pdf",
                    }
                ],
                chunk_size=1000,
                chunk_overlap=0,
                subject_id="computer-network",
            )

        self.assertEqual(written, 1)
        write_rows.assert_called_once()
        metadata = write_rows.call_args.args[1][0]["metadata"]
        self.assertEqual(metadata["mapping_status"], "unmapped")
        self.assertEqual(metadata["concept_id"], "")
        self.assertEqual(save_chunk.call_args.args[0]["mapping_status"], "unmapped")

    def test_upsert_documents_with_summary_returns_request_scoped_mapping_counts(self) -> None:
        class _FakeEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

        with (
            patch("app.services.rag.vector_store.get_embedding_function", return_value=_FakeEmbeddings()),
            patch("app.services.rag.vector_store.delete_source_documents", return_value=0),
            patch("app.services.rag.vector_store.delete_kb_chunks_by_source", return_value=0),
            patch("app.services.rag.vector_store.save_kb_chunk_record"),
            patch("app.services.rag.vector_store.upsert_embedding_rows", return_value=2),
        ):
            summary = upsert_documents_with_summary(
                [
                    "HTTP 默认端口是 80，HTTPS 默认端口是 443。",
                    "这段文本只讨论番茄的颜色和厨房收纳。",
                ],
                metadatas=[
                    {
                        "subject_id": "computer-network",
                        "doc_type": "pdf",
                        "source": "network.pdf",
                        "source_id": "network.pdf",
                    },
                    {
                        "subject_id": "computer-network",
                        "doc_type": "pdf",
                        "source": "unknown.pdf",
                        "source_id": "unknown.pdf",
                    },
                ],
                chunk_size=1000,
                chunk_overlap=0,
                subject_id="computer-network",
            )

        self.assertEqual(summary.inserted_chunks, 2)
        self.assertEqual(summary.mapped_chunks, 1)
        self.assertEqual(summary.unmapped_chunks, 1)

    def test_shared_ingest_deletes_kb_chunks_without_empty_user_filter(self) -> None:
        class _FakeEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

        with (
            patch("app.services.rag.vector_store.get_embedding_function", return_value=_FakeEmbeddings()),
            patch("app.services.rag.vector_store.delete_source_documents", return_value=0),
            patch("app.services.rag.vector_store.delete_kb_chunks_by_source", return_value=0) as delete_chunks,
            patch("app.services.rag.vector_store.save_kb_chunk_record"),
            patch("app.services.rag.vector_store.upsert_embedding_rows", return_value=1),
        ):
            upsert_documents(
                ["HTTP 默认端口是 80。"],
                metadatas=[
                    {
                        "subject_id": "computer-network",
                        "doc_type": "pdf",
                        "source": "network.pdf",
                        "source_id": "network.pdf",
                    }
                ],
                chunk_size=1000,
                chunk_overlap=0,
                subject_id="computer-network",
            )

        delete_chunks.assert_called_once_with(
            subject_id="computer-network",
            source_file="network.pdf",
            source_id="network.pdf",
            doc_type="pdf",
            user_id=None,
        )

    def test_kb_chunk_record_failure_cleans_inserted_vectors_and_raises(self) -> None:
        class _FakeEmbeddings:
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

        with (
            patch("app.services.rag.vector_store.get_embedding_function", return_value=_FakeEmbeddings()),
            patch("app.services.rag.vector_store.delete_source_documents", return_value=0) as delete_source,
            patch("app.services.rag.vector_store.delete_kb_chunks_by_source", return_value=0),
            patch("app.services.rag.vector_store.save_kb_chunk_record", side_effect=RuntimeError("kb down")),
            patch("app.services.rag.vector_store.upsert_embedding_rows", return_value=1),
        ):
            with self.assertRaises(RuntimeError):
                upsert_documents(
                    ["HTTP 默认端口是 80。"],
                    metadatas=[
                        {
                            "subject_id": "computer-network",
                            "doc_type": "pdf",
                            "source": "network.pdf",
                            "source_id": "network.pdf",
                        }
                    ],
                    chunk_size=1000,
                    chunk_overlap=0,
                    subject_id="computer-network",
                )

        self.assertGreaterEqual(delete_source.call_count, 2)
        delete_source.assert_any_call(
            subject_id="computer-network",
            source_id="network.pdf",
            doc_type="pdf",
            user_id=None,
        )


if __name__ == "__main__":
    unittest.main()
