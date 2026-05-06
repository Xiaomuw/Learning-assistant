from __future__ import annotations

import re
from typing import Any

from app.shared.schemas.contracts import PendingCheckState, TeachingPolicyDecision


_SMALLTALK_PATTERNS = [
    r"^(你好|您好|嗨|hi|hello|hey|在吗|早上好|晚上好)[！!。.\s]*$",
    r"(好烦|焦虑|难受|不想学|崩溃|累死了)",
    r"^(你是谁|你是什么|你能做什么)$",
]
_PROBLEM_PATTERNS = [
    r"(计算|求解|求证|证明|怎么做|哪里错|报错|写一个|写个|排序函数|代码)",
    r"```",
    r"\d+\s*[+\-*/×÷]\s*\d+",
]
_CONCEPT_PATTERNS = [
    r"^(什么是|什么叫|解释一下|解释下|怎么理解|什么意思|介绍一下)",
    r"(是什么|概念|原理)",
]
_COMPARE_PATTERNS = [
    r"(.+)和(.+)(区别|不同|优劣|哪个好|哪个更|怎么选)",
    r"(区别|对比|比较).*(和|与|vs)",
    r"(.+)\s+vs\s+(.+)",
]
_APPLICATION_PATTERNS = [
    r"(用在哪里|什么时候用|怎么用|应用场景|举个例子|场景|适合用|不适合用)",
]
_REVIEW_PATTERNS = [
    r"(复习|巩固|重新过一遍|再过一遍|回顾|薄弱点|错题)",
]

_STUCK_PATTERNS = [r"(不会|不懂|没明白|卡住|完全不会|还是不会)"]
_WRONG_PATTERNS = [r"(错了|不对|答案错|运行不对|结果不对)"]
_NEW_INTENT_PATTERNS = [
    *_SMALLTALK_PATTERNS,
    *_PROBLEM_PATTERNS,
    *_CONCEPT_PATTERNS,
    *_COMPARE_PATTERNS,
    *_APPLICATION_PATTERNS,
    *_REVIEW_PATTERNS,
]

_DEFAULT_ANALOGIES = {
    "HTTP": "把 HTTP 想成前台点餐：浏览器递出点菜单，服务器按菜单把内容端回来。",
    "TCP": "把 TCP 想成可靠快递：每个包裹都有编号，丢了会补发，顺序乱了会重新排好。",
    "RAG": "把 RAG 想成开卷考试：模型先翻资料，再根据翻到的内容组织回答。",
}

_DEFINITIONS = {
    "HTTP": "HTTP 是浏览器和服务器之间传递网页请求与响应的应用层协议。",
    "TCP": "TCP（Transmission Control Protocol）是一种面向连接、可靠、有序传输字节流的传输层协议。",
    "RAG": "RAG 是先检索知识库资料、再让模型基于资料回答的问答方法。",
}

_CHECKS = {
    "HTTP": "如果浏览器访问网页失败，你觉得 HTTP 负责的是“页面内容请求响应”，还是“把每个数据包可靠送达”？",
    "TCP": "如果一段数据丢了，TCP 会倾向于重传，还是直接忽略这段数据？",
    "RAG": "如果知识库没有相关资料，RAG 的回答更可能变准还是更容易退回通用解释？",
}

_EXPECTED_KEYWORDS = {
    "HTTP": ["请求", "响应", "应用层", "网页", "服务器"],
    "TCP": ["可靠", "连接", "重传", "顺序", "传输层"],
    "RAG": ["检索", "知识库", "资料", "回答"],
}


def _matches(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _has_new_intent(question: str) -> bool:
    return _matches(_NEW_INTENT_PATTERNS, question.strip())


def classify_teaching_input(question: str, router_type: str, pending_check: dict[str, Any] | None) -> str:
    normalized = question.strip()
    if pending_check and not _has_new_intent(normalized):
        return "check_answer"
    if _matches(_SMALLTALK_PATTERNS, normalized):
        return "smalltalk"
    if _matches(_PROBLEM_PATTERNS, normalized):
        return "problem"
    if _matches(_CONCEPT_PATTERNS, normalized):
        return "concept"
    if _matches(_COMPARE_PATTERNS, normalized):
        return "compare"
    if _matches(_APPLICATION_PATTERNS, normalized):
        return "application"
    if _matches(_REVIEW_PATTERNS, normalized):
        return "review"
    if router_type in {"problem", "review", "smalltalk"}:
        return router_type
    return "concept"


def extract_knowledge_point(question: str, fallback: str = "") -> str:
    upper_hits = re.findall(r"\b(HTTP|HTTPS|TCP|UDP|IP|RAG|REST|SQL|BFS|DFS)\b", question, re.IGNORECASE)
    if upper_hits:
        return upper_hits[0].upper()

    cleaned = re.sub(
        r"^(什么是|什么叫|解释一下|解释下|怎么理解|什么意思|介绍一下|帮我复习一下|复习一下)",
        "",
        question.strip(),
    )
    cleaned = re.sub(r"[？?。！，!,\s]+$", "", cleaned).strip()
    if cleaned:
        return cleaned[:40]
    return fallback or "当前知识点"


def _pick_analogy(knowledge_point: str, session_memory: dict[str, Any], memory: dict[str, Any]) -> str:
    used = []
    used.extend(list(session_memory.get("used_analogies", []) or []))
    used.extend(list(memory.get("used_analogies", []) or []))
    for item in used:
        if isinstance(item, dict) and item.get("knowledge_point") == knowledge_point and item.get("analogy"):
            return str(item["analogy"])
    return _DEFAULT_ANALOGIES.get(
        knowledge_point,
        f"把「{knowledge_point}」先当成一件工具：它出现，是为了解决某类反复出现的问题。",
    )


def _find_mastery_score(knowledge_point: str, mastery_items: list[dict[str, Any]]) -> float | None:
    for item in mastery_items:
        if str(item.get("knowledge_point", "") or "") == knowledge_point:
            try:
                return float(item.get("mastery_score", 0.0) or 0.0)
            except (TypeError, ValueError):
                return None
    return None


def decide_teaching_policy(
    *,
    question: str,
    router_type: str,
    memory: dict[str, Any],
    session_memory: dict[str, Any],
    mastery_items: list[dict[str, Any]],
) -> TeachingPolicyDecision:
    pending_raw = session_memory.get("pending_check") if isinstance(session_memory, dict) else None
    pending = PendingCheckState.model_validate(pending_raw) if isinstance(pending_raw, dict) else None
    teaching_input_type = classify_teaching_input(question, router_type, pending_raw if pending else None)
    knowledge_point = (
        pending.knowledge_point if teaching_input_type == "check_answer" and pending
        else extract_knowledge_point(question, str(session_memory.get("active_topic", "") or ""))
    )
    mastery_score = _find_mastery_score(knowledge_point, mastery_items)

    if teaching_input_type == "check_answer":
        user_state = "check_answer"
    elif _matches(_STUCK_PATTERNS, question):
        user_state = "stuck"
    elif _matches(_WRONG_PATTERNS, question):
        user_state = "answer_wrong"
    elif teaching_input_type == "problem":
        user_state = "practicing"
    elif mastery_score is None:
        user_state = "first_contact"
    elif mastery_score < 60:
        user_state = "fuzzy"
    else:
        user_state = "first_contact"

    stuck_count = int(session_memory.get("stuck_count", 0) or 0)
    if user_state == "stuck":
        stuck_count += 1

    used_analogy = _pick_analogy(knowledge_point, session_memory, memory)
    return TeachingPolicyDecision(
        teaching_input_type=teaching_input_type,
        teaching_user_state=user_state,
        knowledge_point=knowledge_point,
        mastery_score=mastery_score,
        used_analogy=used_analogy,
        pending_check=pending,
        stuck_count=stuck_count,
        should_wait_for_user=teaching_input_type in {"concept", "problem", "review", "check_answer", "application"},
        last_teaching_action="decide",
    )


def _definition(knowledge_point: str) -> str:
    return _DEFINITIONS.get(knowledge_point, f"{knowledge_point} 是一个用于解决特定问题的知识点。")


def _check(knowledge_point: str) -> str:
    return _CHECKS.get(knowledge_point, f"你能用一句话说说「{knowledge_point}」主要解决什么问题吗？")


def _pending(knowledge_point: str, teaching_input_type: str, prompt: str) -> dict[str, Any]:
    return PendingCheckState(
        knowledge_point=knowledge_point,
        teaching_input_type=teaching_input_type,
        prompt=prompt,
        expected_keywords=_EXPECTED_KEYWORDS.get(knowledge_point, [knowledge_point]),
    ).model_dump()


def _score_check_answer(answer: str, pending: PendingCheckState | None) -> tuple[bool, str]:
    if not pending:
        return False, "没有找到上一轮的检查点，我先按新问题处理。"
    keywords = [kw for kw in pending.expected_keywords if kw]
    matched = [kw for kw in keywords if kw.lower() in answer.lower()]
    if not keywords:
        return len(answer.strip()) >= 4, "你已经给出了自己的理解。"
    if matched:
        return True, f"你提到了「{matched[0]}」，方向是对的。"
    return False, f"你还没有碰到关键点：{keywords[0]}。"


def _wants_guided_response(question: str) -> bool:
    return _matches(
        [
            r"(提示|引导|先别告诉答案|不要直接给答案|别直接给答案)",
            r"(让我自己想|让我自己做|苏格拉底|反问我|先问我)",
        ],
        question,
    )


def _wants_short_answer(question: str) -> bool:
    return _matches([r"(一句话|只要答案|直接回答|简短|不用展开)"], question)


def _has_existing_explanation(existing_explanation: dict[str, Any] | None) -> bool:
    if not existing_explanation:
        return False
    if str(existing_explanation.get("thinking", "") or "").strip():
        return True
    return any(str(item).strip() for item in list(existing_explanation.get("steps", []) or []))


def _has_example_step(steps: list[str]) -> bool:
    return any(("例" in step or "EXAMPLE" in step or "SCENE" in step) for step in steps)


def _example_for(knowledge_point: str, question: str) -> str:
    normalized = f"{knowledge_point} {question}".lower()
    if "http" in normalized:
        return "EXAMPLE: 你在浏览器输入网址时，浏览器发出 HTTP 请求，服务器返回 HTML 或 JSON，这就是一次请求-响应。"
    if "tcp" in normalized:
        return "EXAMPLE: 下载文件时，TCP 会保证数据分片按顺序到达，丢包时会重传，所以文件不会缺一块。"
    if "rag" in normalized:
        return "EXAMPLE: 你问笔记本里的知识点时，系统先检索相关资料，再让模型基于这些片段组织回答。"
    return f"EXAMPLE: 可以把「{knowledge_point}」放进一个具体任务里看：先确认问题需要它解决什么，再看它如何降低复杂度。"


def _preserve_existing_explanation_response(
    decision: TeachingPolicyDecision,
    *,
    question: str,
    existing_explanation: dict[str, Any],
    existing_final_answer: str,
) -> dict[str, Any]:
    knowledge_point = decision.knowledge_point or str(existing_explanation.get("topic", "") or "当前知识点")
    steps = [str(item) for item in list(existing_explanation.get("steps", []) or []) if str(item).strip()]
    thinking = str(existing_explanation.get("thinking", "") or "").strip()
    if not steps and thinking:
        steps = [thinking]
    if not _wants_short_answer(question) and not _has_example_step(steps):
        steps.append(_example_for(knowledge_point, question))

    explanation = {
        "topic": str(existing_explanation.get("topic", "") or knowledge_point),
        "thinking": thinking or (steps[0] if steps else _definition(knowledge_point)),
        "steps": steps,
        "mistakes": str(existing_explanation.get("mistakes", "") or ""),
        "similar": [
            str(item)
            for item in list(existing_explanation.get("similar", []) or [knowledge_point])[:3]
            if str(item).strip()
        ],
    }
    final_answer = (
        existing_final_answer.strip()
        or str(existing_explanation.get("final_answer", "") or "").strip()
        or explanation["thinking"]
    )
    return {
        "explanation": explanation,
        "final_answer": final_answer,
        "teaching_phase": "completed",
        "last_teaching_action": f"{decision.teaching_input_type}_direct",
        "teaching_waiting_for_user": False,
    }


def build_teaching_response(
    decision: TeachingPolicyDecision,
    *,
    question: str,
    existing_explanation: dict[str, Any] | None = None,
    existing_final_answer: str = "",
    code_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把教学策略决策转换为兼容现有 Explanation 的响应更新。"""
    knowledge_point = decision.knowledge_point or "当前知识点"
    input_type = decision.teaching_input_type
    user_state = decision.teaching_user_state
    pending_update: dict[str, Any] | None = None
    clear_pending = False

    if (
        input_type in {"concept", "application"}
        and _has_existing_explanation(existing_explanation)
        and not _wants_guided_response(question)
    ):
        return _preserve_existing_explanation_response(
            decision,
            question=question,
            existing_explanation=dict(existing_explanation or {}),
            existing_final_answer=existing_final_answer,
        )

    if input_type == "smalltalk":
        steps = ["我在，我们可以慢慢来。你现在想练习，还是想理解一个概念？"]
        final_answer = steps[0]
        action = "smalltalk"
    elif input_type == "compare":
        steps = [
            f"CORE_DIFF: 「{knowledge_point}」这组概念的核心差异，先看它们解决的问题是否相同。",
            "TABLE: 维度 | A | B；关注目标、工作层级、典型场景这 3 个维度即可。",
            "WHEN_TO_USE: 当你能说清“我要解决什么问题”时，选择通常就清楚了。",
        ]
        final_answer = "核心比较先抓目标、层级和使用场景。"
        action = "compare"
    elif input_type == "application":
        check = f"如果换成你自己的项目，你觉得哪里适合用「{knowledge_point}」？"
        steps = [
            f"SCENE: 先想一个具体场景：你遇到一个需要「{knowledge_point}」解决的问题。",
            f"WHY_HERE: 这个场景需要它，是因为它能处理「{knowledge_point}」对应的核心矛盾。",
            f"COUNTER: 如果问题本身不需要这个能力，硬用它反而会增加复杂度。",
            f"CHECK: {check}",
        ]
        final_answer = check
        pending_update = _pending(knowledge_point, "application", check)
        action = "application_check"
    elif input_type == "review":
        recall = f"RECALL: 你先说说你还记得「{knowledge_point}」的哪一部分？"
        steps = [recall]
        final_answer = recall
        pending_update = _pending(knowledge_point, "review", recall)
        action = "review_recall"
    elif input_type == "problem":
        if code_result and code_result.get("executed"):
            if code_result.get("success"):
                steps = ["你的代码或计算结果通过了受限验证。"]
                final_answer = "✓ 验证通过"
                clear_pending = True
                action = "code_verified"
            else:
                hint = code_result.get("hint") or "第一个关键步骤方向偏了，你再想想。"
                steps = [f"HINT: {hint}"]
                final_answer = hint
                action = "code_retry"
        elif user_state == "answer_wrong":
            locate = "LOCATE: 你的思路是什么？先告诉我你从哪一步开始推的。"
            steps = [locate]
            final_answer = locate
            pending_update = _pending(knowledge_point, "problem", locate)
            action = "locate"
        elif user_state == "stuck" and decision.stuck_count >= 2:
            steps = [
                f"SCAFFOLD: 这题先抓住「{knowledge_point}」这个关键点。",
                "完整思路：先列已知条件，再确定要用的规则，最后代入或验证边界。",
            ]
            final_answer = "我先把完整解题骨架给你，下一轮我们只修你卡住的那一步。"
            action = "full_solution_after_two_stucks"
        elif user_state == "stuck":
            scaffold = f"SCAFFOLD: 这题需要先用到「{knowledge_point}」，你知道它在这里怎么用吗？"
            steps = [scaffold]
            final_answer = scaffold
            pending_update = _pending(knowledge_point, "problem", scaffold)
            action = "scaffold"
        else:
            hint = f"HINT: 先别急着算答案，第一步是判断这题和「{knowledge_point}」的哪条规则有关。"
            steps = [hint]
            final_answer = hint
            pending_update = _pending(knowledge_point, "problem", hint)
            action = "hint"
    elif input_type == "check_answer":
        ok, feedback = _score_check_answer(question, decision.pending_check)
        if ok:
            steps = [f"SUMMARY: {feedback} 我们先把这个点记为已推进。"]
            final_answer = "方向对了。你可以继续追问这个点的下一层。"
            clear_pending = True
            action = "check_passed"
        else:
            prompt = decision.pending_check.prompt if decision.pending_check else _check(knowledge_point)
            steps = [
                f"GAP: {feedback}",
                f"CHECK: 换个说法再试一次：{prompt}",
            ]
            final_answer = prompt
            pending_update = _pending(knowledge_point, "concept", prompt)
            action = "check_retry"
    else:
        if user_state == "fuzzy":
            recall = f"RECALL: 你记得「{knowledge_point}」的哪一部分？先说你记得的就好。"
            steps = [recall]
            final_answer = recall
            pending_update = _pending(knowledge_point, "concept", recall)
            action = "recall"
        else:
            check = _check(knowledge_point)
            steps = [
                f"WHY: 需要「{knowledge_point}」，是因为它解决了学习和工程里一个反复出现的问题。",
                f"ANALOGY: {decision.used_analogy}",
                f"DEFINITION: {_definition(knowledge_point)}",
                f"CHECK: {check}",
            ]
            final_answer = check
            pending_update = _pending(knowledge_point, "concept", check)
            action = "concept_check"

    should_mark_weak = user_state in {"stuck", "answer_wrong"} or action in {"check_retry", "code_retry"}
    explanation = {
        "topic": knowledge_point,
        "thinking": steps[0] if steps else final_answer,
        "steps": steps,
        "mistakes": f"如果这里卡住，优先复盘「{knowledge_point}」。" if should_mark_weak else "",
        "similar": [knowledge_point],
    }
    if existing_explanation and input_type in {"compare", "application"}:
        similar = existing_explanation.get("similar")
        if isinstance(similar, list) and similar:
            explanation["similar"] = [str(item) for item in similar[:3]]

    update: dict[str, Any] = {
        "explanation": explanation,
        "final_answer": final_answer,
        "teaching_phase": "waiting" if pending_update else "completed",
        "last_teaching_action": action,
        "teaching_waiting_for_user": bool(pending_update),
        "answer_guard_applied": True,
        "answer_guard_reason": f"teaching_policy:{action}",
    }
    if pending_update:
        update["pending_check"] = pending_update
    if clear_pending:
        update["pending_check"] = {}
    return update
