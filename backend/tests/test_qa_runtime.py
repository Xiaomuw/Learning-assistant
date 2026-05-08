from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@127.0.0.1:5432/__tests_only__",
)

from app.orchestration.agents.qa_agent import qa_agent
from app.domains.memory.long_term import build_long_term_context
from app.domains.qa import explanation_fallback as explainer_module
from app.domains.qa.explanation_fallback import ExplanationOutput, explain_for_qa_fallback
from app.domains.qa.mode_selection import select_execution_mode
from app.domains.qa.prompts import (
    build_tool_system_message,
    format_user_style_instruction as format_qa_user_style_instruction,
)
from app.domains.qa.runtime import QARuntimeAgent
from app.domains.qa.tracing import build_qa_trace_outputs
from app.domains.practice.common import format_user_style_instruction as format_practice_user_style_instruction
from app.infrastructure.llm.provider import get_model_profile
from app.infrastructure.llm.structured import invoke_with_schema
from app.shared.schemas.model_profile import ModelProfile
from app.domains.qa.middleware import postprocess_middleware, preprocess_middleware
from app.domains.qa.schemas import AgentExecutionResult, AgentRequest, AnswerSchema, ToolCall
from app.domains.qa.capability_tools import tool_executor, tool_registry


class QARuntimeTest(unittest.TestCase):
    def test_known_and_unknown_model_profiles(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_BASE_URL": "https://api.openai.com/v1"},
            clear=False,
        ):
            known = get_model_profile("openai-gpt-4o")
        self.assertTrue(known.supports_tool_calling)
        self.assertTrue(known.supports_structured_output)
        self.assertIn("image", known.supported_modalities)

        unknown = get_model_profile("totally-unknown-model")
        self.assertFalse(unknown.supports_tool_calling)
        self.assertFalse(unknown.supports_structured_output)
        self.assertEqual(unknown.supported_modalities, ("text",))

    def test_qa_trace_outputs_include_tool_and_source_observability(self) -> None:
        result = AgentExecutionResult(
            execution_mode="tool_calling",
            retrieved_docs=[{"content": "HTTP 缓存", "score": 0.9}],
            retrieval_diagnosis={"diagnosis": "ready", "raw_count": 3},
            tool_calls=[
                {"name": "notebook_retrieve", "capability": "notebook_retrieve", "success": True, "doc_count": 1},
                {"name": "web_search", "capability": "web_search", "provider": "tavily", "success": True, "doc_count": 2},
            ],
            tool_decision_rounds=[{"round": 1}, {"round": 2}],
            source_usage="mixed",
            final_answer="HTTP 缓存可以复用响应。",
            primary_model_id="llama3.3-70b-instruct",
            fallback_model_id="qwen3-coder-flash",
            fallback_used=True,
            fallback_reason="unauthorized_model",
        )

        outputs = build_qa_trace_outputs(result)

        self.assertEqual(outputs["tool_decision_rounds_count"], 2)
        self.assertEqual(outputs["source_usage"], "mixed")
        self.assertEqual(outputs["verified_context_count"], 1)
        self.assertEqual(outputs["raw_retrieved_count"], 3)
        self.assertTrue(outputs["used_web_search"])
        self.assertTrue(outputs["used_notebook"])
        self.assertTrue(outputs["fallback_used"])
        self.assertEqual(outputs["primary_model_id"], "llama3.3-70b-instruct")
        self.assertEqual(outputs["fallback_model_id"], "qwen3-coder-flash")

    def test_digital_ocean_endpoint_disables_native_tool_and_structured_by_default(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
                "LLM_ENABLE_TOOL_CALLING": "false",
                "LLM_ENABLE_STRUCTURED_OUTPUT": "false",
            },
            clear=False,
        ):
            profile = get_model_profile("openai-gpt-oss-20b")

        self.assertFalse(profile.supports_tool_calling)
        self.assertFalse(profile.supports_structured_output)

    def test_digital_ocean_endpoint_allows_native_capabilities_when_opted_in(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_BASE_URL": "https://inference.do-ai.run/v1",
                "LLM_ENABLE_TOOL_CALLING": "true",
                "LLM_ENABLE_STRUCTURED_OUTPUT": "true",
            },
            clear=False,
        ):
            profile = get_model_profile("openai-gpt-oss-20b")

        self.assertTrue(profile.supports_tool_calling)
        self.assertTrue(profile.supports_structured_output)

    def test_mode_selection_respects_route_guard_boundaries(self) -> None:
        profile = ModelProfile(
            model_id="tool-model",
            provider="Test",
            family="Test",
            supports_tool_calling=True,
            supports_structured_output=True,
            context_window=16_000,
            supported_modalities=("text",),
        )

        explain_request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="network",
            subject_name="计算机网络",
            subject_description="",
            question="什么是 HTTP？",
            question_type="concept",
            runtime_context={
                "route": "explain",
                "guard": {"allow_tools": False, "allow_search": False},
            },
        )
        self.assertEqual(select_execution_mode(explain_request, profile), "structured_output")

        agent_request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="",
            question="帮我搜索一下最新 GPT-5 API 变化",
            question_type="concept",
            runtime_context={
                "route": "agent",
                "guard": {"allow_tools": True, "allow_search": True},
            },
        )
        self.assertEqual(select_execution_mode(agent_request, profile), "tool_calling")

        rag_request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="network",
            subject_name="计算机网络",
            subject_description="",
            question="根据当前资料解释 HTTP",
            question_type="concept",
            runtime_context={
                "route": "rag",
                "guard": {"allow_tools": True, "allow_search": False},
            },
        )
        self.assertEqual(select_execution_mode(rag_request, profile), "tool_calling")

        precomputed_rag_request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="network",
            subject_name="计算机网络",
            subject_description="",
            question="根据当前资料解释 HTTP",
            question_type="concept",
            runtime_context={
                "route": "rag",
                "guard": {"allow_tools": True, "allow_search": False},
                "rag_precomputed": True,
                "rag_ready": False,
            },
        )
        self.assertEqual(select_execution_mode(precomputed_rag_request, profile), "tool_calling")

    def test_user_style_is_silenced_in_prompt_helpers_and_long_term_context(self) -> None:
        qa_instruction = format_qa_user_style_instruction("严格导师", "先批评再回答")
        practice_instruction = format_practice_user_style_instruction("严格导师", "先批评再回答")
        long_term = build_long_term_context(
            {
                "display_name": "测试用户",
                "agent_style_name": "严格导师",
                "agent_style_prompt": "先批评再回答",
            },
            {"recent_topics": ["HTTP"]},
        )

        self.assertIn("暂时禁用", qa_instruction)
        self.assertIn("暂时禁用", practice_instruction)
        self.assertNotIn("严格导师", qa_instruction)
        self.assertNotIn("先批评", practice_instruction)
        self.assertNotIn("严格导师", long_term)
        self.assertNotIn("先批评", long_term)

    def test_tool_prompt_includes_route_and_guard_policy(self) -> None:
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="",
            question="帮我查最新资料",
            question_type="concept",
            user_style_name="严格导师",
            user_style_prompt="先批评再回答",
            runtime_context={
                "route": "agent",
                "guard": {
                    "allow_tools": True,
                    "allow_search": True,
                    "reason": "需要最新信息",
                },
            },
        )

        prompt = build_tool_system_message(request)

        self.assertIn("route: agent", prompt)
        self.assertIn("allow_tools: True", prompt)
        self.assertIn("allow_search: True", prompt)
        self.assertIn("需要最新信息", prompt)
        self.assertIn("用户自定义风格已暂时禁用", prompt)
        self.assertNotIn("严格导师", prompt)
        self.assertNotIn("先批评", prompt)
        self.assertIn("web_search", prompt)
        self.assertIn("notebook_retrieve", prompt)

    def test_qa_runtime_tool_registry_exposes_capability_names(self) -> None:
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="",
            question="什么是 HTTP？",
            question_type="concept",
            runtime_context={
                "allow_tools": True,
                "allow_search": False,
                "notebook_policy": "optional",
                "search_policy": "forbidden",
            },
        )

        tool_names = {tool.name for tool in tool_registry.get_available_tools(agent_request=request)}

        self.assertIn("notebook_retrieve", tool_names)
        self.assertIn("session_summary", tool_names)
        self.assertIn("learning_profile", tool_names)
        self.assertIn("question_recommend", tool_names)
        self.assertNotIn("web_search", tool_names)
        self.assertNotIn("tavily_web_search", tool_names)
        self.assertNotIn("search_notebook_context", tool_names)

    def test_invoke_with_schema_parses_plain_json_fallback(self) -> None:
        from langchain_core.messages import AIMessage
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.runnables import RunnableLambda

        prompt = ChatPromptTemplate.from_messages([("human", "{question}")])
        fake_llm = RunnableLambda(
            lambda _payload: AIMessage(
                content='```json\n{"topic":"HTTP","thinking":"应用层协议","steps":["请求","响应"],"mistakes":"","similar":["HTTPS","TCP"],"final_answer":"HTTP 是应用层协议。"}\n```'
            )
        )

        result = invoke_with_schema(
            prompt,
            fake_llm,
            AnswerSchema,
            {"question": "什么是 HTTP"},
            model_name="llama3.3-70b-instruct",
            prefer_native=False,
        )

        self.assertEqual(result.topic, "HTTP")
        self.assertEqual(result.final_answer, "HTTP 是应用层协议。")

    def test_preprocess_normalizes_and_summarizes_long_inputs(self) -> None:
        profile = ModelProfile(
            model_id="test-model",
            provider="Test",
            family="Test",
            supports_tool_calling=False,
            supports_structured_output=True,
            context_window=500,
            supported_modalities=("text",),
            max_output_tokens=512,
        )
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="  这是 一个   很长 的 简介  " * 80,
            question="   请   帮我   解释   HTTP   缓存   ",
            question_type="concept",
            short_term_context="历史 " * 500,
            session_memory_context="摘要 " * 500,
            long_term_context="长期 " * 500,
        )

        processed = preprocess_middleware(request, profile)

        self.assertEqual(processed.question, "请 帮我 解释 HTTP 缓存")
        self.assertLess(len(processed.short_term_context), len(request.short_term_context))
        self.assertLess(len(processed.long_term_context), len(request.long_term_context))

    def test_preprocess_rejects_unsupported_modalities(self) -> None:
        profile = ModelProfile(
            model_id="text-only",
            provider="Test",
            family="Test",
            supports_tool_calling=False,
            supports_structured_output=False,
            context_window=16_000,
            supported_modalities=("text",),
            max_output_tokens=512,
        )
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="",
            question="看一下这张图",
            question_type="concept",
            input_modalities=("text", "image"),
        )

        with self.assertRaises(ValueError):
            preprocess_middleware(request, profile)

    def test_postprocess_wraps_plain_text_when_no_schema_available(self) -> None:
        profile = ModelProfile(
            model_id="plain",
            provider="Test",
            family="Test",
            supports_tool_calling=False,
            supports_structured_output=False,
            context_window=16_000,
            supported_modalities=("text",),
            max_output_tokens=512,
        )
        result = AgentExecutionResult(
            execution_mode="direct_answer",
            raw_output="HTTP 是一种请求-响应式的应用层协议。",
        )

        processed = postprocess_middleware(result, profile)
        self.assertEqual(processed.answer.topic, "当前问题")
        self.assertIn("HTTP", processed.final_answer)

    def test_tool_executor_reads_session_summary(self) -> None:
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="general",
            subject_name="通用知识",
            subject_description="",
            question="继续讲这个",
            question_type="concept",
            session_memory={
                "summary_text": "当前会话正在围绕 HTTP 缓存学习。",
                "active_topic": "HTTP 缓存",
                "current_goal": "理解协商缓存和强缓存",
                "open_loops": ["继续讲 ETag 和 Last-Modified"],
                "resolved_points": ["已经区分了强缓存和协商缓存"],
            },
        )

        result = tool_executor.execute(
            ToolCall(name="session_summary", args={"include_open_loops": True}),
            agent_request=request,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.payload["active_topic"], "HTTP 缓存")
        self.assertIn("ETag", result.payload["open_loops"][0])

    def test_fact_seeking_rag_fallback_prioritizes_direct_fact_from_retrieved_docs(self) -> None:
        with patch(
            "app.domains.qa.explanation_fallback._invoke_explainer_chain",
            return_value=ExplanationOutput(
                topic="HTTP",
                thinking="建议先检查资料中的端口描述。",
                steps=["回顾 HTTP 和 HTTPS 的区别。"],
                mistakes="不要混淆 HTTP 和 HTTPS。",
                similar=["HTTPS", "TCP"],
            ),
        ):
            result = explain_for_qa_fallback(
                {
                    "question": "HTTP 的默认端口是多少？",
                    "question_type": "concept",
                    "retrieved_docs": [
                        {
                            "content": "HTTP 默认端口是 80。HTTPS 默认端口是 443。",
                            "metadata": {"doc_type": "chapter"},
                            "score": 0.9,
                        }
                    ],
                    "memory": {},
                    "subject_name": "计算机网络",
                }
            )

        explanation = result["explanation"]
        self.assertIn("80", explanation["thinking"])
        self.assertIn("80", explanation["steps"][0])

    def test_no_rag_context_still_uses_json_fallback_for_models_without_native_structured_output(self) -> None:
        with patch(
            "app.domains.qa.explanation_fallback._invoke_explainer_chain",
            return_value=ExplanationOutput(
                topic="HTTP",
                thinking="HTTP 是 Web 中的应用层请求响应协议。",
                steps=["客户端发送请求。", "服务器返回响应。"],
                mistakes="不要把 HTTP 当成传输层协议。",
                similar=["HTTPS", "状态码"],
            ),
        ) as invoke_explainer:
            result = explain_for_qa_fallback(
                {
                    "question": "什么是 HTTP？",
                    "question_type": "concept",
                    "model_name": "openai-gpt-oss-20b",
                    "retrieved_docs": [],
                    "retrieval_diagnosis": {"diagnosis": "no_matching_docs"},
                    "memory": {},
                    "subject_name": "计算机网络",
                }
            )

        invoke_explainer.assert_called_once()
        explanation = result["explanation"]
        self.assertEqual(explanation["topic"], "HTTP")
        self.assertIn("应用层", explanation["thinking"])

    def test_no_rag_context_plain_text_fallback_answers_common_http_question(self) -> None:
        with patch(
            "app.domains.qa.explanation_fallback._invoke_explainer_chain",
            side_effect=RuntimeError("model unavailable"),
        ):
            result = explain_for_qa_fallback(
                {
                    "question": "什么是 HTTP？",
                    "question_type": "concept",
                    "model_name": "openai-gpt-oss-20b",
                    "retrieved_docs": [],
                    "retrieval_diagnosis": {"diagnosis": "no_matching_docs"},
                    "memory": {},
                    "subject_name": "计算机网络",
                }
            )

        explanation = result["explanation"]
        self.assertEqual(explanation["topic"], "HTTP")
        self.assertIn("应用层", explanation["thinking"])
        self.assertNotIn("建议下一步", " ".join(explanation["steps"]))

    def test_no_rag_context_replaces_model_no_context_template_for_common_tcp_question(self) -> None:
        with patch(
            "app.domains.qa.explanation_fallback._invoke_explainer_chain",
            return_value=ExplanationOutput(
                topic="什么是TCP？",
                thinking="当前 notebook 没有检索到足够匹配的问题资料。",
                steps=[
                    "我没有在当前 notebook 中命中能支撑这个问题的高相关内容。",
                    "如果你希望我按通用知识解释，可以直接追问“按通用知识讲一下”。",
                ],
                mistakes="检索低命中时，不要把泛化解释当成当前 notebook 的专属结论。",
                similar=["资料覆盖", "查询改写"],
            ),
        ):
            result = explain_for_qa_fallback(
                {
                    "question": "什么是TCP？",
                    "question_type": "concept",
                    "model_name": "openai-gpt-oss-20b",
                    "retrieved_docs": [],
                    "retrieval_diagnosis": {"diagnosis": "no_matching_docs"},
                    "memory": {},
                    "subject_name": "通用知识",
                }
            )

        explanation = result["explanation"]
        self.assertEqual(explanation["topic"], "TCP")
        self.assertIn("传输层", explanation["thinking"])
        self.assertNotIn("按通用知识解释", " ".join(explanation["steps"]))

    def test_tavily_docs_use_general_fallback_when_model_is_unavailable(self) -> None:
        with patch(
            "app.domains.qa.explanation_fallback._invoke_explainer_chain",
            side_effect=RuntimeError("model unavailable"),
        ):
            result = explain_for_qa_fallback(
                {
                    "question": "什么是TCP？",
                    "question_type": "concept",
                    "model_name": "openai-gpt-oss-20b",
                    "retrieved_docs": [
                        {
                            "content": "TCP 是可靠的传输层协议。",
                            "metadata": {"retrieval_source": "tavily_web"},
                            "score": 0.92,
                        }
                    ],
                    "retrieval_diagnosis": {"diagnosis": "ready"},
                    "memory": {},
                    "subject_name": "通用知识",
                }
            )

        explanation = result["explanation"]
        self.assertEqual(explanation["topic"], "TCP")
        self.assertIn("传输层", explanation["thinking"])
        self.assertIn("网络补充资料", explanation["thinking"])
        self.assertIn("三次握手", " ".join(explanation["steps"]))
        self.assertNotIn("向量检索", " ".join(explanation["similar"]))

    def test_runtime_reuses_precomputed_rag_context_without_retrieving_again(self) -> None:
        profile = ModelProfile(
            model_id="test-model",
            provider="Test",
            family="Test",
            supports_tool_calling=False,
            supports_structured_output=False,
            context_window=16_000,
            supported_modalities=("text",),
        )
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="computer-network",
            subject_name="计算机网络",
            subject_description="",
            question="HTTP 默认端口是多少？",
            question_type="concept",
            model_name="test-model",
            runtime_context={
                "rag_precomputed": True,
                "retrieved_docs": [
                    {
                        "content": "HTTP 默认端口是 80。",
                        "metadata": {"doc_type": "chapter"},
                        "score": 0.9,
                    }
                ],
                "contextual_query": "HTTP 默认端口",
                "retrieval_diagnosis": {"diagnosis": "ready"},
            },
        )

        @contextmanager
        def _fake_trace_run(**_kwargs):
            class _DummyRun:
                metadata: dict[str, object] = {}

                def end(self, **_end_kwargs) -> None:
                    return None

            yield _DummyRun()

        with (
            patch("app.domains.qa.runtime.trace_run", side_effect=_fake_trace_run),
            patch("app.domains.qa.runtime.retrieve_for_qa_fallback") as retrieve_again,
            patch(
                "app.domains.qa.runtime.explain_for_qa_fallback",
                return_value={
                    "explanation": {
                        "topic": "HTTP",
                        "thinking": "HTTP 默认端口是 80。",
                        "steps": ["HTTP 默认端口是 80。"],
                        "mistakes": "",
                        "similar": ["HTTPS", "TCP"],
                    }
                },
            ),
        ):
            result = QARuntimeAgent(
                request=request,
                state=dict(request.runtime_context, question=request.question),
                model_profile=profile,
            ).run()

        retrieve_again.assert_not_called()
        self.assertEqual(result.contextual_query, "HTTP 默认端口")
        self.assertEqual(result.retrieved_docs[0]["score"], 0.9)
        self.assertIn("80", result.final_answer)

    def test_model_unavailable_still_returns_full_teaching_fallback(self) -> None:
        profile = ModelProfile(
            model_id="test-model",
            provider="Test",
            family="Test",
            supports_tool_calling=False,
            supports_structured_output=False,
            context_window=16_000,
            supported_modalities=("text",),
        )
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="data-structure",
            subject_name="数据结构与算法",
            subject_description="",
            question="什么是 HTTP？",
            question_type="concept",
            model_name="test-model",
            memory={
                "recent_topics": ["TCP/IP"],
                "weak_points": ["应用层和传输层区分"],
            },
        )

        @contextmanager
        def _fake_trace_run(**_kwargs):
            class _DummyRun:
                metadata: dict[str, object] = {}

                def end(self, **_end_kwargs) -> None:
                    return None

            yield _DummyRun()

        with (
            patch("app.domains.qa.runtime.trace_run", side_effect=_fake_trace_run),
            patch(
                "app.domains.qa.runtime.retrieve_for_qa_fallback",
                return_value={
                    "retrieved_docs": [],
                    "verified_context": [],
                    "retrieval_diagnosis": {},
                    "contextual_query": "什么是 HTTP？",
                },
            ),
            patch(
                "app.domains.qa.explanation_fallback._invoke_explainer_chain",
                side_effect=RuntimeError("401: model is not available for your subscription tier"),
            ),
        ):
            result = QARuntimeAgent(
                request=request,
                state={
                    "question": request.question,
                    "question_type": request.question_type,
                    "subject_name": request.subject_name,
                    "memory": request.memory,
                },
                model_profile=profile,
            ).run()

        self.assertEqual(result.model_unavailable_reason, "unauthorized_model")
        self.assertIn("HTTP", result.final_answer)
        self.assertIn("请求", result.final_answer)
        self.assertIn("易错点", result.final_answer)
        self.assertIn("结合你的学习记录", result.final_answer)
        self.assertNotIn("401", result.final_answer)
        self.assertNotIn("模型不可用", result.final_answer)

    def test_explainer_chain_tries_configured_fallback_model_once(self) -> None:
        payload = {"question": "什么是 HTTP？"}
        fallback_output = ExplanationOutput(
            topic="HTTP",
            thinking="HTTP 是应用层协议。",
            steps=["它用于客户端和服务器之间传递请求与响应。"],
            mistakes="不要把 HTTP 当成传输层协议。",
            similar=["HTTPS", "TCP"],
        )

        with (
            patch.dict(
                os.environ,
                {"FALLBACK_CHAT_MODEL": "anthropic-claude-3-haiku-20240306"},
                clear=False,
            ),
            patch("app.domains.qa.explanation_fallback._get_llm", return_value=object()),
            patch(
                "app.domains.qa.explanation_fallback.invoke_with_schema",
                side_effect=[
                    RuntimeError("401: model is not available for your subscription tier"),
                    fallback_output,
                ],
            ) as mock_invoke,
        ):
            result = explainer_module._invoke_explainer_chain(
                payload,
                model_name="openai-gpt-4.1",
            )

        self.assertEqual(result.topic, "HTTP")
        self.assertEqual(mock_invoke.call_args_list[0].kwargs["model_name"], "openai-gpt-4.1")
        self.assertEqual(
            mock_invoke.call_args_list[1].kwargs["model_name"],
            "anthropic-claude-3-haiku-20240306",
        )

    def test_runtime_records_primary_to_fallback_model_metadata(self) -> None:
        request = AgentRequest(
            user_id="u1",
            session_id="s1",
            subject_id="computer-network",
            subject_name="计算机网络",
            subject_description="",
            question="什么是 HTTP？",
            question_type="concept",
        )
        profile = ModelProfile(
            model_id="llama3.3-70b-instruct",
            provider="Meta",
            family="Llama",
            supports_tool_calling=False,
            supports_structured_output=True,
            context_window=128000,
        )
        fallback_profile = ModelProfile(
            model_id="qwen3-coder-flash",
            provider="Alibaba",
            family="Qwen",
            supports_tool_calling=False,
            supports_structured_output=True,
            context_window=128000,
        )
        fallback_answer = AnswerSchema(
            topic="HTTP",
            thinking="HTTP 是应用层协议。",
            steps=["它用于客户端和服务器之间传递请求与响应。"],
            mistakes="不要把 HTTP 当成传输层协议。",
            similar=["HTTPS", "TCP"],
            final_answer="HTTP 是应用层协议。",
        )

        with (
            patch.dict(os.environ, {"FALLBACK_CHAT_MODEL": "qwen3-coder-flash"}, clear=False),
            patch(
                "app.domains.qa.runtime.generate_structured_answer",
                side_effect=[
                    RuntimeError("401: model is not available for your subscription tier"),
                    fallback_answer,
                ],
            ),
            patch(
                "app.domains.qa.runtime.get_model_profile",
                return_value=fallback_profile,
            ),
            patch(
                "app.domains.qa.runtime.retrieve_for_qa_fallback",
                return_value={
                    "retrieved_docs": [],
                    "verified_context": [],
                    "retrieval_diagnosis": {},
                    "contextual_query": "什么是 HTTP？",
                },
            ) as mocked_retrieve,
        ):
            result = QARuntimeAgent(
                request=request,
                state={"question": request.question, "question_type": request.question_type},
                model_profile=profile,
            ).run()

        mocked_retrieve.assert_not_called()
        self.assertTrue(result.degraded)
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.primary_model_id, "llama3.3-70b-instruct")
        self.assertEqual(result.fallback_model_id, "qwen3-coder-flash")
        self.assertEqual(result.fallback_reason, "unauthorized_model")
        self.assertEqual(result.selected_model_profile["model_id"], "qwen3-coder-flash")
        self.assertEqual(
            [(item["role"], item["status"]) for item in result.model_attempts],
            [("primary", "failed"), ("fallback", "ok")],
        )

    def test_qa_agent_node_maps_runtime_output_back_to_state(self) -> None:
        runtime_result = AgentExecutionResult(
            execution_mode="structured_output",
            answer=AnswerSchema(
                topic="HTTP",
                thinking="HTTP 是一种应用层协议。",
                steps=["先理解请求与响应", "再理解无状态通信"],
                mistakes="不要把 HTTP 误认为传输层协议",
                similar=["HTTPS", "TCP"],
                final_answer="HTTP 是应用层协议。",
            ),
            retrieved_docs=[{"content": "HTTP 文档片段", "metadata": {}, "score": 0.9}],
            contextual_query="HTTP 是什么",
            selected_model_profile={"model_id": "openai-gpt-4o"},
        )

        with (
            patch("app.orchestration.agents.qa_agent.get_model_profile", return_value=get_model_profile("openai-gpt-4o")),
            patch("app.orchestration.agents.qa_agent.create_agent") as mock_create,
        ):
            mock_create.return_value.run.return_value = runtime_result
            state = qa_agent(
                {
                    "user_id": "u1",
                    "session_id": "s1",
                    "subject_id": "general",
                    "subject_name": "通用知识",
                    "question": "什么是 HTTP？",
                    "question_type": "concept",
                    "model_name": "openai-gpt-4o",
                    "external_tool_calls": [
                        {
                            "name": "web_search",
                            "capability": "web_search",
                            "provider": "tavily",
                            "success": True,
                            "doc_count": 2,
                        }
                    ],
                    "web_search_attempted": True,
                    "web_search_used": True,
                    "web_search_error": "",
                }
            )

        self.assertEqual(state["explanation"]["topic"], "HTTP")
        self.assertEqual(state["execution_mode"], "structured_output")
        self.assertEqual(state["final_answer"], "HTTP 是应用层协议。")
        self.assertTrue(state["web_search_attempted"])
        self.assertTrue(state["web_search_used"])
        self.assertEqual(state["external_tool_calls"][0]["name"], "web_search")

    def test_qa_agent_wraps_root_trace_with_request_mode_and_metadata(self) -> None:
        runtime_result = AgentExecutionResult(
            execution_mode="tool_calling",
            answer=AnswerSchema(
                topic="HTTP 缓存",
                thinking="需要先检索当前笔记本内容，再结合会话摘要组织解释。",
                steps=["读取笔记本", "整理讲解"],
                mistakes="不要把强缓存和协商缓存混为一谈",
                similar=["ETag", "Cache-Control"],
                final_answer="HTTP 缓存分为强缓存和协商缓存。",
            ),
            tool_calls=[{"name": "notebook_retrieve", "capability": "notebook_retrieve", "success": True}],
            degraded=False,
            selected_model_profile={"model_id": "openai-gpt-4o"},
            final_answer="HTTP 缓存分为强缓存和协商缓存。",
        )

        trace_calls: list[dict[str, object]] = []

        class _DummyRun:
            def __init__(self) -> None:
                self.metadata: dict[str, object] = {}
                self.outputs: dict[str, object] | None = None

            def end(self, *, outputs=None, **_kwargs) -> None:
                self.outputs = outputs

        @contextmanager
        def _fake_trace_run(**kwargs):
            run = _DummyRun()
            trace_calls.append({"kwargs": kwargs, "run": run})
            yield run

        @contextmanager
        def _fake_tracing_context(**_kwargs):
            yield

        with (
            patch("app.orchestration.agents.qa_agent.get_model_profile", return_value=get_model_profile("openai-gpt-4o")),
            patch("app.orchestration.agents.qa_agent.create_agent") as mock_create,
            patch("app.orchestration.agents.qa_agent.qa_tracing_context", side_effect=_fake_tracing_context),
            patch("app.orchestration.agents.qa_agent.trace_run", side_effect=_fake_trace_run),
        ):
            mock_create.return_value.run.return_value = runtime_result
            qa_agent(
                {
                    "user_id": "u1",
                    "session_id": "s1",
                    "subject_id": "general",
                    "subject_name": "通用知识",
                    "question": "什么是 HTTP 缓存？",
                    "question_type": "concept",
                    "request_mode": "sse",
                    "model_name": "openai-gpt-4o",
                }
            )

        self.assertEqual(len(trace_calls), 1)
        trace_kwargs = trace_calls[0]["kwargs"]
        trace_run_instance = trace_calls[0]["run"]
        self.assertEqual(trace_kwargs["name"], "chat.sse.qa")
        self.assertEqual(trace_kwargs["metadata"]["user_id"], "u1")
        self.assertEqual(trace_kwargs["metadata"]["session_id"], "s1")
        self.assertEqual(trace_kwargs["metadata"]["selected_model"], "openai-gpt-4o")
        self.assertEqual(trace_run_instance.metadata["execution_mode"], "tool_calling")
        self.assertEqual(trace_run_instance.metadata["tool_calls_count"], 1)
        self.assertEqual(trace_run_instance.outputs["execution_mode"], "tool_calling")
