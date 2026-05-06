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

from app.domains.qa import retrieval_fallback as retriever_module
from app.domains.qa import explanation_fallback as explainer_module
from app.shared.schemas.contracts import RetrievalDiagnostics


class RetrieverFallbackTest(unittest.TestCase):
    def test_empty_knowledge_base_rewrites_then_returns_empty_docs(self) -> None:
        with (
            patch.object(retriever_module, "_retrieve_documents", side_effect=[[], []]),
            patch.object(retriever_module, "_rewrite_query", return_value="HTTP 的核心概念"),
            patch.object(
                retriever_module,
                "diagnose_retrieval",
                return_value=RetrievalDiagnostics(
                    query="什么是 HTTP？",
                    diagnosis="empty_knowledge_base",
                    coverage_level="empty",
                    suggested_actions=["生成知识框架，先补齐章节骨架"],
                ),
            ),
        ):
            result = retriever_module.retrieve_for_qa_fallback(
                {"question": "什么是 HTTP？", "subject_id": "general"}
            )

        self.assertEqual(result["retrieved_docs"], [])
        self.assertTrue(result["is_rewritten"])
        self.assertEqual(result["retrieval_diagnosis"]["diagnosis"], "empty_knowledge_base")

    def test_context_dependent_question_gets_topic_anchor(self) -> None:
        with (
            patch.object(retriever_module, "_retrieve_documents", return_value=[]),
            patch.object(retriever_module, "_score_documents", return_value=[]),
            patch.object(retriever_module, "_rewrite_query", return_value="HTTP 缓存 为什么会这样"),
            patch.object(
                retriever_module,
                "diagnose_retrieval",
                return_value=RetrievalDiagnostics(
                    query="HTTP 缓存 为什么会这样？",
                    diagnosis="no_matching_docs",
                    coverage_level="partial",
                ),
            ),
        ):
            result = retriever_module.retrieve_for_qa_fallback(
                {
                    "question": "那为什么会这样？",
                    "subject_id": "general",
                    "memory": {"recent_topics": ["HTTP 缓存"]},
                    "short_term_messages": [
                        {
                            "role": "assistant",
                            "content": "我们刚刚在讲 HTTP 缓存。",
                            "explanation": {"topic": "HTTP 缓存"},
                        }
                    ],
                }
            )

        self.assertTrue(result["contextual_query"].startswith("HTTP 缓存"))

    def test_empty_notebook_explainer_distinguishes_notebook_miss_from_general_answer(self) -> None:
        with patch.object(
            explainer_module,
            "_invoke_explainer_chain",
            side_effect=RuntimeError("model unavailable"),
        ):
            result = explainer_module.explain_for_qa_fallback(
                {
                    "question": "HTTP 默认端口是多少？",
                    "subject_name": "计算机网络",
                    "retrieved_docs": [],
                    "retrieval_diagnosis": {
                        "diagnosis": "empty_knowledge_base",
                        "suggested_actions": ["上传 PDF 或添加 URL，让 notebook 有真实资料来源"],
                    },
                }
            )

        explanation = result["explanation"]
        self.assertIn("当前 notebook 未命中", explanation["thinking"])
        self.assertIn("HTTP", explanation["thinking"])
        self.assertIn("请求-响应", " ".join(explanation["steps"]))


if __name__ == "__main__":
    unittest.main()
