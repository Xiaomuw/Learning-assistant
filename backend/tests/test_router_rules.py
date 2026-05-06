from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.agents import router as router_module


class RouterRulesTest(unittest.TestCase):
    def test_meta_questions_are_classified_by_rules(self) -> None:
        result = router_module.router_agent({"question": "你是什么模型？"})
        self.assertEqual(result["question_type"], "meta")
        self.assertEqual(result["route"], "fast")

    def test_knowledge_base_content_question_is_not_meta(self) -> None:
        result = router_module.router_agent({"question": "PGVector 在这个知识库里做什么？一句话。"})
        self.assertEqual(result["question_type"], "concept")
        self.assertEqual(result["route"], "rag")

    def test_smalltalk_questions_are_classified_by_rules(self) -> None:
        result = router_module.router_agent({"question": "你好"})
        self.assertEqual(result["question_type"], "smalltalk")
        self.assertEqual(result["route"], "fast")

    def test_practice_questions_are_classified_by_rules(self) -> None:
        result = router_module.router_agent({"question": "给我出两道数据库索引题"})
        self.assertEqual(result["question_type"], "practice")
        self.assertEqual(result["route"], "explain")

    def test_review_questions_are_classified_by_rules(self) -> None:
        result = router_module.router_agent({"question": "帮我复习 HTTP 缓存"})
        self.assertEqual(result["question_type"], "review")
        self.assertEqual(result["route"], "explain")

    def test_problem_questions_are_classified_by_rules(self) -> None:
        result = router_module.router_agent({"question": "这道题怎么做？"})
        self.assertEqual(result["question_type"], "problem")
        self.assertEqual(result["route"], "explain")

    def test_mcq_questions_are_classified_by_rules(self) -> None:
        result = router_module.router_agent(
            {
                "question": (
                    "下面这道选择题选什么？\n"
                    "HTTP 默认端口是？\n"
                    "A. 20\nB. 53\nC. 80\nD. 443"
                )
            }
        )
        self.assertEqual(result["question_type"], "mcq_problem")
        self.assertEqual(result["route"], "explain")

    def test_notebook_context_routes_to_rag(self) -> None:
        result = router_module.router_agent(
            {
                "question": "根据当前 PDF 解释一下事务隔离级别",
                "subject_id": "computer-network",
            }
        )
        self.assertEqual(result["question_type"], "concept")
        self.assertEqual(result["route"], "rag")
        self.assertEqual(result["notebook_policy"], "required")
        self.assertFalse(result["notebook_required"])
        self.assertEqual(result["answer_mode"], "hybrid")
        self.assertEqual(result["search_policy"], "allowed")

    def test_strict_notebook_question_disables_external_fallback(self) -> None:
        result = router_module.router_agent(
            {
                "question": "只根据我的 notebook 解释 HTTP，不要用通用知识",
                "subject_id": "computer-network",
            }
        )
        self.assertEqual(result["question_type"], "concept")
        self.assertEqual(result["route"], "rag")
        self.assertEqual(result["notebook_policy"], "strict")
        self.assertTrue(result["notebook_required"])
        self.assertEqual(result["answer_mode"], "notebook_grounded")
        self.assertEqual(result["search_policy"], "forbidden")

    def test_latest_or_search_questions_route_to_agent(self) -> None:
        result = router_module.router_agent({"question": "帮我搜索一下最新 GPT-5 API 变化"})
        self.assertEqual(result["question_type"], "concept")
        self.assertEqual(result["route"], "agent")
        self.assertEqual(result["search_policy"], "required")
        self.assertTrue(result["external_search_required"])

    def test_stable_general_concept_skips_notebook_and_search(self) -> None:
        result = router_module.router_agent({"question": "什么是 HTTP？"})
        self.assertEqual(result["question_type"], "concept")
        self.assertEqual(result["route"], "explain")
        self.assertEqual(result["notebook_policy"], "skip")
        self.assertFalse(result["notebook_required"])
        self.assertEqual(result["answer_mode"], "general_teaching")
        self.assertEqual(result["search_policy"], "allowed")

    def test_selected_canonical_notebook_does_not_force_rag_for_stable_concept(self) -> None:
        result = router_module.router_agent(
            {"question": "什么是 HTTP？", "subject_id": "data-structure"}
        )

        self.assertEqual(result["question_type"], "concept")
        self.assertEqual(result["route"], "explain")
        self.assertEqual(result["notebook_policy"], "skip")
        self.assertEqual(result["answer_mode"], "general_teaching")

    def test_current_browser_support_requires_search(self) -> None:
        result = router_module.router_agent({"question": "HTTP/3 现在浏览器支持怎么样？"})
        self.assertEqual(result["route"], "agent")
        self.assertEqual(result["search_policy"], "required")

    def test_context_dependent_concept_followup_is_rewritten(self) -> None:
        result = router_module.router_agent(
            {
                "question": "能给我讲一下概念不？",
                "session_memory": {"active_topic": "HTTP"},
                "memory": {},
            }
        )
        self.assertIn("HTTP", result["contextual_question"])
        self.assertEqual(result["route"], "explain")

    def test_llm_fallback_uses_structured_router_output(self) -> None:
        structured = router_module.RouterOutput(
            question_type="concept",
            confidence=0.97,
            reasoning="structured output fallback",
        )
        with patch.object(router_module, "_invoke_router_chain", return_value=structured):
            result = router_module.router_agent({"question": "请解释一下 TCP 慢启动"})

        self.assertEqual(result["question_type"], "concept")
        self.assertEqual(result["route"], "explain")


if __name__ == "__main__":
    unittest.main()
