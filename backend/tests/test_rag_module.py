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

from app.orchestration.agents.rag import rag_agent
from app.orchestration.agents.context_audit import context_audit_agent
from app.services.rag.vector_store import search_documents
from app.services.rag.retriever import filter_relevant_documents
from app.orchestration.agents.web_search import web_search_agent
from app.services.rag.loader import build_chapter_document, question_bank_item_to_document
from app.services.rag.rag_service import RagContextResult
from app.services.rag.splitter import split_text
from app.shared.schemas.contracts import RetrievalDiagnostics, RetrievedDocument


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

    def test_rag_node_writes_retrieval_context(self) -> None:
        result = RagContextResult(
            raw_docs=[
                RetrievedDocument(
                    doc_id="doc-1",
                    content="HTTP 默认端口是 80。",
                    metadata={"doc_type": "chapter"},
                    score=0.9,
                )
            ],
            docs=[
                RetrievedDocument(
                    doc_id="doc-1",
                    content="HTTP 默认端口是 80。",
                    metadata={"doc_type": "chapter"},
                    score=0.9,
                )
            ],
            diagnosis=RetrievalDiagnostics(
                query="HTTP 默认端口",
                hit_count=1,
                top_score=0.9,
                diagnosis="ready",
                coverage_level="ready",
            ),
            contextual_query="HTTP 默认端口",
            rag_ready=True,
        )

        with patch("app.orchestration.agents.rag.retrieve_context", return_value=result):
            update = rag_agent(
                {
                    "question": "HTTP 默认端口是多少？",
                    "subject_id": "computer-network",
                    "memory": {},
                }
            )

        self.assertTrue(update["rag_precomputed"])
        self.assertFalse(update["rag_ready"])
        self.assertEqual(update["raw_retrieved_docs"][0]["content"], "HTTP 默认端口是 80。")
        self.assertEqual(update["retrieved_docs"], [])
        self.assertEqual(update["retrieval_diagnosis"]["diagnosis"], "ready")

    def test_rag_node_fail_open_on_retrieval_error(self) -> None:
        with (
            patch.dict(os.environ, {"TAVILY_API_KEY": ""}, clear=False),
            patch("app.orchestration.agents.rag.retrieve_context", side_effect=RuntimeError("db down")),
        ):
            update = rag_agent({"question": "HTTP", "subject_id": "computer-network"})

        self.assertTrue(update["rag_precomputed"])
        self.assertFalse(update["rag_ready"])
        self.assertEqual(update["retrieved_docs"], [])
        self.assertIn("rag_node failed", update["graph_warnings"][0])

    def test_rag_node_marks_web_search_required_when_notebook_context_is_not_ready(self) -> None:
        result = RagContextResult(
            docs=[],
            diagnosis=RetrievalDiagnostics(
                query="什么是 HTTP",
                hit_count=0,
                top_score=0.0,
                diagnosis="no_matching_docs",
                coverage_level="partial",
            ),
            contextual_query="什么是 HTTP",
            rag_ready=False,
        )

        with patch("app.orchestration.agents.rag.retrieve_context", return_value=result):
            update = rag_agent(
                {
                    "question": "什么是 HTTP",
                    "question_type": "concept",
                    "subject_id": "computer-network",
                    "search_policy": "allowed",
                    "memory": {},
                }
            )

        self.assertFalse(update["rag_ready"])
        self.assertTrue(update["web_search_required"])
        self.assertEqual(update["retrieved_docs"], [])
        self.assertEqual(update["retrieval_diagnosis"]["diagnosis"], "no_matching_docs")

    def test_rag_node_discards_irrelevant_notebook_context(self) -> None:
        result = RagContextResult(
            docs=[],
            diagnosis=RetrievalDiagnostics(
                query="什么是 HTTP",
                hit_count=0,
                top_score=0.0,
                diagnosis="no_matching_docs",
                coverage_level="partial",
            ),
            contextual_query="什么是 HTTP",
            rag_ready=False,
            relevance={
                "query": "什么是 HTTP",
                "raw_count": 1,
                "kept_count": 0,
                "discarded_count": 1,
                "reason": "no_core_term_overlap",
                "key_terms": ["http"],
            },
        )

        with patch("app.orchestration.agents.rag.retrieve_context", return_value=result):
            update = rag_agent(
                {
                    "question": "什么是 HTTP",
                    "question_type": "concept",
                    "subject_id": "computer-network",
                    "notebook_policy": "optional",
                    "search_policy": "forbidden",
                    "memory": {},
                }
            )

        self.assertFalse(update["rag_ready"])
        self.assertEqual(update["retrieved_docs"], [])
        self.assertEqual(update["retrieval_relevance"]["reason"], "no_core_term_overlap")
        self.assertFalse(update["web_search_required"])

    def test_context_audit_verifies_relevant_notebook_context(self) -> None:
        update = context_audit_agent(
            {
                "question": "HTTP 默认端口是多少？",
                "notebook_policy": "required",
                "raw_retrieved_docs": [
                    {
                        "doc_id": "doc-1",
                        "content": "HTTP 默认端口是 80。",
                        "metadata": {"doc_type": "chapter"},
                        "score": 0.9,
                    }
                ],
                "retrieval_diagnosis": {"diagnosis": "ready", "hit_count": 1, "top_score": 0.9},
            }
        )

        self.assertTrue(update["context_audit"]["usable"])
        self.assertTrue(update["rag_ready"])
        self.assertEqual(update["verified_context"][0]["content"], "HTTP 默认端口是 80。")
        self.assertTrue(update["notebook_retrieved"])
        self.assertFalse(update["notebook_required"])
        self.assertEqual(update["answer_mode"], "hybrid")
        self.assertIn("HTTP 默认端口", update["notebook_context"])

    def test_context_audit_discards_irrelevant_notebook_context(self) -> None:
        update = context_audit_agent(
            {
                "question": "什么是 HTTP？",
                "notebook_policy": "optional",
                "raw_retrieved_docs": [
                    {
                        "doc_id": "doc-ask-better",
                        "content": "如何提出更可检索的问题。向学习助手提问时，问题越具体越容易得到有用回答。",
                        "metadata": {"title": "提问技巧"},
                        "score": 0.82,
                    }
                ],
                "retrieval_diagnosis": {"diagnosis": "ready", "hit_count": 1, "top_score": 0.82},
            }
        )

        self.assertFalse(update["context_audit"]["usable"])
        self.assertEqual(update["context_audit"]["reason"], "generic_advice_not_answer_context")
        self.assertEqual(update["verified_context"], [])
        self.assertFalse(update["rag_ready"])
        self.assertTrue(update["notebook_retrieved"])
        self.assertFalse(update["notebook_required"])
        self.assertEqual(update["answer_mode"], "general_teaching")
        self.assertEqual(update["notebook_context"], "")

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

    def test_web_search_node_uses_tavily_when_notebook_context_is_not_ready(self) -> None:
        tavily_result = {
            "documents": [
                {
                    "content": "HTTP 是一种应用层请求响应协议。",
                    "metadata": {"retrieval_source": "tavily_web", "source": "tavily_summary"},
                    "score": 0.92,
                    "distance": 0.08,
                }
            ],
            "attempted": True,
            "used": True,
            "tool_call": {
                "name": "tavily_web_search",
                "args": {"query": "什么是 HTTP", "max_results": 5},
                "success": True,
                "doc_count": 1,
                "external": True,
            },
            "error": "",
        }

        with patch("app.orchestration.agents.web_search.call_tavily_search", return_value=tavily_result):
            update = web_search_agent(
                {
                    "question": "什么是 HTTP",
                    "question_type": "concept",
                    "subject_id": "computer-network",
                    "retrieved_docs": [],
                    "retrieval_diagnosis": {"diagnosis": "no_matching_docs"},
                    "rag_ready": False,
                }
            )

        self.assertTrue(update["rag_ready"])
        self.assertTrue(update["web_search_attempted"])
        self.assertTrue(update["web_search_used"])
        self.assertEqual(update["retrieved_docs"][0]["metadata"]["retrieval_source"], "tavily_web")
        self.assertEqual(update["external_tool_calls"][0]["name"], "tavily_web_search")
        self.assertEqual(update["retrieval_diagnosis"]["diagnosis"], "ready")

    def test_web_search_node_records_tavily_unconfigured_as_visible_tool_failure(self) -> None:
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}, clear=False):
            update = web_search_agent(
                {
                    "question": "什么是 TCP",
                    "question_type": "concept",
                    "subject_id": "computer-network",
                    "retrieved_docs": [],
                    "retrieval_diagnosis": {"diagnosis": "no_matching_docs"},
                    "rag_ready": False,
                }
            )

        self.assertFalse(update["rag_ready"])
        self.assertTrue(update["web_search_attempted"])
        self.assertFalse(update["web_search_used"])
        self.assertEqual(update["web_search_error"], "tavily_unconfigured")
        self.assertEqual(update["external_tool_calls"][0]["name"], "tavily_web_search")
        self.assertFalse(update["external_tool_calls"][0]["success"])

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
