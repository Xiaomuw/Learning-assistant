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

from app.domains.memory import session_summary as session_memory_module


class SessionMemoryTest(unittest.TestCase):
    def test_meta_turn_keeps_existing_learning_topic(self) -> None:
        result = session_memory_module.update_session_memory(
            previous_session_memory={
                "summary_text": "当前会话正在围绕 HTTP 学习。",
                "active_topic": "HTTP",
                "current_goal": "理解 HTTP 的基本概念",
                "open_loops": ["继续追问缓存与连接管理"],
                "resolved_points": ["已经解释了 HTTP 是应用层协议"],
                "last_question_type": "concept",
                "last_updated_at": "2026-04-15T00:00:00Z",
            },
            short_term_messages=[],
            short_term_context="（当前会话暂无历史上下文）",
            long_term_context="（暂无长期学习记忆）",
            question="你是什么模型？",
            question_type="meta",
            explanation={"topic": "当前对话模型", "thinking": "当前模型是 ..."},
            quiz_items=[],
            final_answer="当前模型是 ...",
            subject_name="通用知识",
        )

        self.assertEqual(result["active_topic"], "HTTP")
        self.assertEqual(result["current_goal"], "理解 HTTP 的基本概念")
        self.assertEqual(result["summary_text"], "当前会话正在围绕 HTTP 学习。")

    def test_rule_summary_falls_back_when_llm_enhancement_fails(self) -> None:
        with patch.object(
            session_memory_module,
            "_invoke_session_memory_enhancement",
            side_effect=RuntimeError("summary model timeout"),
        ):
            result = session_memory_module.update_session_memory(
                previous_session_memory={},
                short_term_messages=[
                    {"role": "user", "content": "什么是 HTTP？"},
                    {"role": "assistant", "content": "HTTP 是应用层协议。", "explanation": {"topic": "HTTP"}},
                ],
                short_term_context="学生1: 什么是 HTTP？\n助手2（主题：HTTP）: HTTP 是应用层协议。",
                long_term_context="用户昵称：测试用户",
                question="那为什么会这样？",
                question_type="concept",
                explanation={
                    "topic": "HTTP",
                    "thinking": "HTTP 定义了请求与响应的语义。",
                    "steps": ["先理解应用层职责", "再看请求与响应"],
                },
                quiz_items=[],
                final_answer="HTTP 定义了请求与响应的语义。",
                subject_name="通用知识",
            )

        self.assertEqual(result["active_topic"], "HTTP")
        self.assertTrue(result["summary_text"])
        self.assertEqual(result["last_question_type"], "concept")

    def test_failed_practice_quality_gate_does_not_replace_active_topic(self) -> None:
        result = session_memory_module.update_session_memory(
            previous_session_memory={
                "summary_text": "当前会话正在围绕 HTTP 学习。",
                "active_topic": "HTTP",
                "current_goal": "理解 HTTP 的基本概念",
                "open_loops": [],
                "resolved_points": [],
                "last_question_type": "concept",
            },
            short_term_messages=[],
            short_term_context="学生1: 给我出两道数据库索引练习题",
            long_term_context="（暂无长期学习记忆）",
            question="给我出两道数据库索引练习题",
            question_type="practice",
            explanation={
                "topic": "容易把 HTTP 的 80 和 HTTPS 的 443 混淆",
                "thinking": "围绕「容易把 HTTP 的 80 和 HTTPS 的 443 混淆」的出题未通过质量门，本轮没有保存题目。",
                "steps": [],
            },
            quiz_items=[],
            final_answer="围绕「容易把 HTTP 的 80 和 HTTPS 的 443 混淆」的出题未通过质量门，本轮没有保存题目。",
            subject_name="数据结构与算法",
        )

        self.assertEqual(result["active_topic"], "HTTP")
        self.assertNotIn("HTTP 的 80 和 HTTPS 的 443 混淆", result["active_topic"])


if __name__ == "__main__":
    unittest.main()
