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

from app.domains.practice.quiz_request import build_quiz_clarification_panel, resolve_quiz_request


class QuizRequestResolverTest(unittest.TestCase):
    def test_continue_generation_inherits_last_topic(self) -> None:
        result = resolve_quiz_request("帮我再出一些题", {"last_topic": "HTTP"})

        self.assertTrue(result.is_quiz_request)
        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.intent, "continue_quiz_generation")
        self.assertEqual(result.topic, "HTTP")
        self.assertIsNone(result.requested_topic)
        self.assertEqual(result.previous_topic, "HTTP")
        self.assertEqual(result.active_topic, "HTTP")
        self.assertFalse(result.should_switch_topic)
        self.assertEqual(result.source, "last_topic")
        self.assertEqual(result.target_module, "practice")

    def test_explicit_data_structure_request_switches_from_http(self) -> None:
        result = resolve_quiz_request("生成一些有关数据结构的题目", {"last_topic": "HTTP"})

        self.assertTrue(result.is_quiz_request)
        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.intent, "quiz_generation")
        self.assertEqual(result.topic, "数据结构与算法")
        self.assertEqual(result.subject_id, "data-structure")
        self.assertEqual(result.requested_topic, "数据结构与算法")
        self.assertEqual(result.previous_topic, "HTTP")
        self.assertEqual(result.active_topic, "数据结构与算法")
        self.assertTrue(result.should_switch_topic)

    def test_explicit_data_structure_related_noise_switches_from_http(self) -> None:
        result = resolve_quiz_request("帮我出一些有关数据与结构有关的题目", {"last_topic": "HTTP"})

        self.assertTrue(result.is_quiz_request)
        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.intent, "quiz_generation")
        self.assertEqual(result.topic, "数据结构与算法")
        self.assertEqual(result.subject_id, "data-structure")
        self.assertEqual(result.requested_topic, "数据结构与算法")
        self.assertEqual(result.previous_topic, "HTTP")
        self.assertEqual(result.active_topic, "数据结构与算法")
        self.assertTrue(result.should_switch_topic)

    def test_explicit_data_structure_specific_subtopic_is_preserved(self) -> None:
        result = resolve_quiz_request("帮我出一些数据结构里的栈和队列题", {"last_topic": "HTTP"})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "栈和队列")
        self.assertEqual(result.subject_id, "data-structure")
        self.assertEqual(result.requested_topic, "栈和队列")
        self.assertEqual(result.previous_topic, "HTTP")
        self.assertTrue(result.should_switch_topic)

    def test_missing_context_returns_clarification_panel(self) -> None:
        result = resolve_quiz_request("帮我出点题", {})
        panel = build_quiz_clarification_panel(result)

        self.assertEqual(result.action, "clarify_quiz_request")
        self.assertTrue(result.need_clarification)
        self.assertEqual(result.clarification_reason, "missing_topic")
        self.assertGreater(len(panel.recommended_options), 0)
        self.assertGreater(len(panel.question_type_options), 0)
        self.assertGreater(len(panel.difficulty_options), 0)
        self.assertGreater(len(panel.count_options), 0)
        self.assertIn("HashMap", panel.custom_input_placeholder)

    def test_explicit_topic_type_and_count_generates_pack(self) -> None:
        result = resolve_quiz_request("围绕 HashMap 出 5 道单选题", {})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "HashMap")
        self.assertEqual(result.source, "explicit_user_input")
        self.assertEqual(result.question_type, "single_choice")
        self.assertEqual(result.count, 5)

    def test_explicit_data_structure_single_choice_keeps_subject_topic(self) -> None:
        result = resolve_quiz_request("给我出5道数据结构的单选题", {"last_topic": "HTTP"})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "数据结构与算法")
        self.assertEqual(result.subject_id, "data-structure")
        self.assertEqual(result.requested_topic, "数据结构与算法")
        self.assertEqual(result.question_type, "single_choice")
        self.assertEqual(result.count, 5)
        self.assertNotEqual(result.topic, "单选")

    def test_english_practice_question_request_extracts_topic_and_count(self) -> None:
        result = resolve_quiz_request("Generate two stack practice questions", {})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "stack")
        self.assertEqual(result.count, 2)
        self.assertEqual(result.question_type, "single_choice")
        self.assertEqual(result.source, "explicit_user_input")

    def test_english_quiz_me_request_extracts_topic(self) -> None:
        result = resolve_quiz_request("quiz me on HashMap", {})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "HashMap")

    def test_english_mcq_request_extracts_topic_and_count(self) -> None:
        result = resolve_quiz_request("create 3 MCQs about TCP", {})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "TCP")
        self.assertEqual(result.count, 3)

    def test_chinese_topic_generation_overrides_failed_http_topic(self) -> None:
        result = resolve_quiz_request(
            "给我出两道数据库索引练习题",
            {"last_topic": "容易把 HTTP 的 80 和 HTTPS 的 443 混淆"},
        )

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.intent, "quiz_generation")
        self.assertEqual(result.topic, "数据库索引")
        self.assertEqual(result.requested_topic, "数据库索引")
        self.assertEqual(result.active_topic, "数据库索引")
        self.assertEqual(result.source, "explicit_user_input")
        self.assertTrue(result.should_switch_topic)
        self.assertFalse(result.need_clarification)

    def test_continuation_without_explicit_topic_still_inherits_last_topic(self) -> None:
        result = resolve_quiz_request("再来两道", {"last_topic": "HTTP"})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.intent, "continue_quiz_generation")
        self.assertEqual(result.topic, "HTTP")
        self.assertIsNone(result.requested_topic)
        self.assertEqual(result.active_topic, "HTTP")
        self.assertFalse(result.should_switch_topic)

    def test_explicit_data_structure_subject_overrides_last_topic(self) -> None:
        result = resolve_quiz_request("出一些数据与结构类型的题目给我", {"last_topic": "TCP"})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "数据结构与算法")
        self.assertEqual(result.subject_id, "data-structure")
        self.assertEqual(result.source, "explicit_user_input")

    def test_explicit_canonical_subject_alias_overrides_recent_udp(self) -> None:
        result = resolve_quiz_request("出一些数据结构与算法类型的题目给我", {"last_topic": "UDP"})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "数据结构与算法")
        self.assertEqual(result.subject_id, "data-structure")
        self.assertEqual(result.source, "explicit_user_input")

    def test_explicit_computer_network_subject_maps_subject_id(self) -> None:
        result = resolve_quiz_request("出一些计算机网络类型的题目给我", {"last_topic": "HashMap"})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "计算机网络")
        self.assertEqual(result.subject_id, "computer-network")
        self.assertEqual(result.source, "explicit_user_input")

    def test_explicit_computer_network_single_choice_keeps_subject_topic(self) -> None:
        result = resolve_quiz_request("再出2道计算机网络的单选题", {"last_topic": "数据结构与算法"})

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "计算机网络")
        self.assertEqual(result.subject_id, "computer-network")
        self.assertEqual(result.requested_topic, "计算机网络")
        self.assertEqual(result.question_type, "single_choice")
        self.assertEqual(result.count, 2)

    def test_ai_refill_uses_current_practice_question(self) -> None:
        result = resolve_quiz_request(
            "AI补题",
            {"current_practice_question": {"knowledge_point": "HashMap", "question": "HashMap 的扩容机制是？"}},
        )

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "HashMap")
        self.assertEqual(result.source, "current_question")

    def test_ai_refill_uses_context_topic_when_current_question_has_no_topic(self) -> None:
        result = resolve_quiz_request(
            "AI补题",
            {
                "current_practice_question": {"question": "下面哪个说法正确？"},
                "topic": "栈",
            },
        )

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "栈")
        self.assertEqual(result.source, "last_topic")

    def test_explicit_http_quiz_request_overrides_stale_dns_context(self) -> None:
        result = resolve_quiz_request(
            "给我出两道 HTTP 单选题\n请只给题目和选项",
            {"last_topic": "DNS", "active_topic": "DNS"},
        )

        self.assertEqual(result.action, "generate_practice_pack")
        self.assertEqual(result.topic, "HTTP")
        self.assertEqual(result.requested_topic, "HTTP")
        self.assertEqual(result.previous_topic, "DNS")
        self.assertEqual(result.active_topic, "HTTP")
        self.assertEqual(result.count, 2)
        self.assertEqual(result.subject_id, "computer-network")
        self.assertTrue(result.should_switch_topic)

    def test_normal_question_does_not_enter_quiz_flow(self) -> None:
        result = resolve_quiz_request("HashMap 为什么线程不安全", {})

        self.assertFalse(result.is_quiz_request)
        self.assertEqual(result.action, "normal_qa")
        self.assertEqual(result.target_module, "qa")


if __name__ == "__main__":
    unittest.main()
