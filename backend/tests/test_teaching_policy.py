from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.domains.teaching.policy import build_teaching_response, decide_teaching_policy
from app.services.code_execution import execute_code


class TeachingPolicyTest(unittest.TestCase):
    def test_concept_first_contact_asks_single_check(self) -> None:
        decision = decide_teaching_policy(
            question="什么是 HTTP？",
            router_type="concept",
            memory={},
            session_memory={},
            mastery_items=[],
        )
        update = build_teaching_response(decision, question="什么是 HTTP？")

        self.assertEqual(decision.teaching_input_type, "concept")
        self.assertEqual(decision.teaching_user_state, "first_contact")
        self.assertTrue(update["teaching_waiting_for_user"])
        self.assertEqual(update["last_teaching_action"], "concept_check")
        steps = update["explanation"]["steps"]
        self.assertEqual(len([item for item in steps if item.startswith("CHECK:")]), 1)
        self.assertTrue(any(item.startswith("WHY:") for item in steps))
        self.assertTrue(any(item.startswith("ANALOGY:") for item in steps))
        self.assertTrue(any(item.startswith("DEFINITION:") for item in steps))
        self.assertEqual(update["pending_check"]["knowledge_point"], "HTTP")

    def test_pending_check_answer_is_scored_before_new_teaching(self) -> None:
        session_memory = {
            "pending_check": {
                "knowledge_point": "HTTP",
                "prompt": "HTTP 负责请求响应还是可靠送达？",
                "expected_keywords": ["请求", "响应", "服务器"],
                "teaching_input_type": "concept",
            }
        }
        decision = decide_teaching_policy(
            question="它负责浏览器和服务器之间的请求和响应",
            router_type="concept",
            memory={},
            session_memory=session_memory,
            mastery_items=[],
        )
        update = build_teaching_response(decision, question="它负责浏览器和服务器之间的请求和响应")

        self.assertEqual(decision.teaching_input_type, "check_answer")
        self.assertEqual(update["last_teaching_action"], "check_passed")
        self.assertFalse(update["teaching_waiting_for_user"])
        self.assertEqual(update["pending_check"], {})

    def test_fuzzy_concept_starts_with_recall(self) -> None:
        decision = decide_teaching_policy(
            question="解释一下 TCP",
            router_type="concept",
            memory={},
            session_memory={},
            mastery_items=[{"knowledge_point": "TCP", "mastery_score": 42}],
        )
        update = build_teaching_response(decision, question="解释一下 TCP")

        self.assertEqual(decision.teaching_user_state, "fuzzy")
        self.assertEqual(update["last_teaching_action"], "recall")
        self.assertTrue(update["explanation"]["steps"][0].startswith("RECALL:"))

    def test_concept_preserves_existing_direct_explanation(self) -> None:
        decision = decide_teaching_policy(
            question="什么是 HTTP？",
            router_type="concept",
            memory={},
            session_memory={},
            mastery_items=[],
        )
        update = build_teaching_response(
            decision,
            question="什么是 HTTP？",
            existing_final_answer="HTTP 是浏览器和服务器之间传递请求与响应的应用层协议。",
            existing_explanation={
                "topic": "HTTP",
                "thinking": "HTTP 是一种应用层请求响应协议。",
                "steps": ["定义：HTTP 规定客户端如何请求资源，服务器如何返回响应。"],
                "mistakes": "",
                "similar": ["HTTPS", "TCP"],
            },
        )

        self.assertFalse(update["teaching_waiting_for_user"])
        self.assertEqual(update["last_teaching_action"], "concept_direct")
        self.assertIn("应用层协议", update["final_answer"])
        self.assertTrue(any("EXAMPLE" in item for item in update["explanation"]["steps"]))
        self.assertNotIn("pending_check", update)

    def test_compare_and_application_are_separate_from_plain_concept(self) -> None:
        compare = decide_teaching_policy(
            question="HTTP 和 HTTPS 有什么区别？",
            router_type="concept",
            memory={},
            session_memory={},
            mastery_items=[],
        )
        application = decide_teaching_policy(
            question="递归用在哪里？",
            router_type="concept",
            memory={},
            session_memory={},
            mastery_items=[],
        )

        self.assertEqual(compare.teaching_input_type, "compare")
        self.assertEqual(application.teaching_input_type, "application")

    def test_problem_uses_hint_before_answer(self) -> None:
        decision = decide_teaching_policy(
            question="帮我做一下这道排序题",
            router_type="problem",
            memory={},
            session_memory={},
            mastery_items=[],
        )
        update = build_teaching_response(decision, question="帮我做一下这道排序题")

        self.assertEqual(decision.teaching_user_state, "practicing")
        self.assertEqual(update["last_teaching_action"], "hint")
        self.assertTrue(update["final_answer"].startswith("HINT:"))

    def test_execute_code_verifies_expression_and_blocks_dangerous_code(self) -> None:
        expression = execute_code("计算 2+3×4")
        dangerous = execute_code("```python\nopen('/tmp/x', 'w').write('bad')\n```")

        self.assertTrue(expression.executed)
        self.assertTrue(expression.success)
        self.assertEqual(expression.stdout, "14")
        self.assertTrue(dangerous.executed)
        self.assertTrue(dangerous.blocked)
        self.assertFalse(dangerous.success)


if __name__ == "__main__":
    unittest.main()
