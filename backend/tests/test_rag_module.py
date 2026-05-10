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

from app.services.rag.vector_store import search_documents
from app.services.rag.retriever import filter_relevant_documents
from app.services.rag.loader import build_chapter_document, question_bank_item_to_document
from app.services.rag.splitter import split_text
from app.shared.schemas.contracts import RetrievedDocument


class RagModuleTest(unittest.TestCase):
    def test_loader_builds_chapter_metadata(self) -> None:
        document = build_chapter_document(
            subject_id="computer-network",
            title="HTTP",
            content="HTTP 默认端口是 80。",
            source_id="seed:computer-network:http",
        )

        self.assertIn("HTTP 默认端口", document.content)
        self.assertEqual(document.metadata["subject_id"], "computer-network")
        self.assertEqual(document.metadata["doc_type"], "chapter")
        self.assertEqual(document.metadata["knowledge_point"], "HTTP")

    def test_loader_builds_question_bank_document(self) -> None:
        document = question_bank_item_to_document(
            {
                "id": "q1",
                "question_id": "q1",
                "subject_id": "database",
                "knowledge_point": "事务",
                "question": "事务的隔离性属于 ACID 中哪一项？",
                "options": [{"key": "A", "text": "Isolation"}],
                "correct_option": "A",
                "explanation": "隔离性对应 Isolation。",
                "option_rationales": {"A": "正确"},
            }
        )

        self.assertIn("事务的隔离性", document.content)
        self.assertEqual(document.metadata["doc_type"], "question_bank")
        self.assertEqual(document.metadata["source_id"], "q1")

    def test_splitter_returns_chunks_for_long_text(self) -> None:
        chunks = split_text("HTTP 默认端口是 80。" * 40, chunk_size=80, chunk_overlap=10)
        self.assertGreater(len(chunks), 1)

    def test_relevance_filter_drops_high_score_context_without_core_entity(self) -> None:
        docs = [
            RetrievedDocument(
                doc_id="doc-ask-better",
                content="如何提出更可检索的问题。向学习助手提问时，问题越具体越容易得到有用回答。",
                metadata={"title": "提问技巧"},
                score=0.82,
            )
        ]

        filtered, relevance = filter_relevant_documents(query="什么是 HTTP？", docs=docs, threshold=0.65)

        self.assertEqual(filtered, [])
        self.assertEqual(relevance["reason"], "no_core_term_overlap")
        self.assertIn("http", relevance["key_terms"])

    def test_search_documents_falls_back_to_keyword_search_when_vector_search_fails(self) -> None:
        keyword_docs = [
            {
                "doc_id": "keyword-1",
                "content": "HTTP 是应用层协议。",
                "metadata": {"retrieval_source": "keyword_fallback"},
                "score": 0.7,
                "distance": 0.3,
            }
        ]
        with (
            patch(
                "app.services.rag.vector_store._search_collection_documents",
                side_effect=RuntimeError("embedding denied"),
            ),
            patch(
                "app.services.rag.vector_store._keyword_search_documents",
                return_value=keyword_docs,
            ),
        ):
            docs = search_documents(query="HTTP", subject_id="computer-network")

        self.assertEqual(docs, keyword_docs)
        self.assertEqual(docs[0]["metadata"]["retrieval_source"], "keyword_fallback")


if __name__ == "__main__":
    unittest.main()
