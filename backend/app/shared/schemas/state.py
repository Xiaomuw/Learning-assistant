"""
LangGraph TypedDict State 定义
==============================
所有 Agent 共享的全局状态对象。
LangGraph 会在节点之间自动传递和合并 State。
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict

from app.shared.schemas.model_profile import ModelProfile


# ---------- 子结构：结构化讲解 ----------
class Explanation(TypedDict, total=False):
    """讲解 Agent 输出的结构化解释"""
    topic: str                  # 所属知识点/主题
    thinking: str               # 解题思路 / 概念推导过程
    steps: list[str]            # 分步讲解
    mistakes: str               # 当前最值得提醒的易错点
    similar: list[str]          # 相似题目 / 延伸知识点


# ---------- 子结构：学习记忆 ----------
class Memory(TypedDict, total=False):
    """记忆 Agent 维护的用户学习画像"""
    weak_points: list[str]      # 薄弱知识点列表
    error_count: dict[str, int] # 各知识点错误计数  { "二次函数": 3, ... }
    recent_topics: list[str]    # 最近学习的知识点（按时间倒序）
    last_session: str           # 上次会话标识（session_id + 时间戳）
    last_question_type: str     # 上一轮问题类型，供路由 Agent 追问继承使用


# ---------- 子结构：中期会话摘要 ----------
class SessionMemory(TypedDict, total=False):
    """当前会话的中期记忆摘要"""
    summary_text: str
    active_topic: str
    current_goal: str
    open_loops: list[str]
    resolved_points: list[str]
    last_question_type: str
    last_updated_at: str
    pending_check: dict[str, Any]
    teaching_phase: str
    stuck_count: int
    last_teaching_action: str
    used_analogies: list[dict[str, str]]


# ---------- 子结构：选择题选项 ----------
class QuizOption(TypedDict):
    """单选题的单个选项"""
    key: Literal["A", "B", "C", "D"]
    text: str


# ---------- 子结构：练习题 ----------
class QuizItem(TypedDict, total=False):
    """出题 Agent 生成的单道单选题"""
    difficulty: Literal["基础", "变式", "易错"]  # 出题难度
    question: str               # 题目正文
    options: list[QuizOption]   # 固定为 4 个选项（A/B/C/D）
    correct_option: Literal["A", "B", "C", "D"]  # 正确选项
    explanation: str            # 完整解析
    option_rationales: dict[str, str]  # 每个选项对应的对/错说明
    knowledge_point: str        # 对应知识点
    source_type: Literal["question_bank", "ai_generated"]  # 题目来源
    source_name: str            # 题目来源名称，如试卷名
    source_year: int | None     # 来源年份
    question_id: str            # 题库题的主键或 AI 题的摘要 ID
    hint: str                   # 可选提示（方向性，不直接给答案）


class QuizGenerationStatus(TypedDict, total=False):
    """练习题生成过程的降级与补题状态。"""
    requested_count: int
    generated_count: int
    question_bank_count: int
    ai_count: int
    fallback_count: int
    partial: bool
    degraded_reason: str
    quality_passed: bool
    retry_count: int
    focus_points: list[str]
    rag_doc_count: int
    quality_issues: list[str]


# ---------- 子结构：图级错误与观测 ----------
class GraphError(TypedDict, total=False):
    """LangGraph 节点未处理异常的脱敏摘要。"""
    node: str
    error_type: str
    message: str
    recoverable: bool


class NodeTiming(TypedDict):
    """单个 LangGraph 节点的耗时观测。"""
    node: str
    elapsed_seconds: float


class GraphPerformanceSummary(TypedDict, total=False):
    """LangGraph 本轮执行的汇总性能观测。"""
    node_count: int
    total_node_seconds: float
    slowest_node: str
    slowest_node_seconds: float
    degraded: bool
    warning_count: int


# ---------- 主 State ----------
class AgentState(TypedDict, total=False):
    """
    LangGraph 全局 State
    ---------------------
    每个 Agent 节点从 state 中读取所需字段，处理后将结果写回 state。
    使用 `total=False` 使所有字段可选，方便各节点按需填充。

    节点读写契约（当前实现）：
      - preflight_node : 读 question/user_id/session_id/subject_id；写 normalized_question/question/graph_warnings/graph_error/route_decision
      - learning_context_node : 读 question；写 learning_context
      - router        : 读 question/learning_context/三层记忆；写 question_type/route/route_confidence/route_reason/notebook_policy/search_policy
      - guard_node    : 读 route/question_type/question/policy；写 guard/allow_tools/allow_search/source_policy
      - rag_node      : 读 question/subject_id/三层记忆；写 raw_retrieved_docs/contextual_query/retrieval_diagnosis/rag_* 诊断字段
      - context_audit_node : 读 raw_retrieved_docs/question/contextual_query；写 verified_context/context_audit/retrieved_docs
      - web_search_node : 读 RAG 诊断与 question；写 Tavily 观测和网络文档上下文
      - qa_agent_node : 读主问答上下文、三层记忆与 RAG 上下文；写 explanation/final_answer/execution_mode/tool_calls/degraded
      - qa_answer_guard_node : 读最终回答；替换低价值资料不足模板
      - mcq_solver    : 读 question/user_style_* / short_term_context / session_memory_context / long_term_context；写 explanation/final_answer
      - quiz_* nodes  : 读 question/explanation/memory/RAG；写 quiz_focus_points/quiz_context/quiz_items/quiz_generation_status/final_answer
      - memory_node   : 读 user_id/session_id/explanation；写 memory
      - meta_node     : 读 question/subject_name/user_style_* / short_term_* / session_memory_* / long_term_context；写 explanation/final_answer
      - graph_error_node : 读 graph_error；写 explanation/final_answer/degraded
      - finalize_node : 读最终输出与观测字段；写 finalized/final_response_type/route_decision
    """

    # ---- 会话标识 ----
    user_id: str                # 用户唯一标识
    session_id: str             # 当前会话 ID

    # ---- 学科 / 笔记本兼容层 ----
    subject_id: str             # 内部兼容命名；产品语义上等价于 notebook_id
    subject_name: str           # 内部兼容命名；产品语义上等价于 notebook_name
    subject_description: str    # 当前笔记本 / 资料库的简介，仅作为知识上下文，不再承担 persona

    # ---- 输入 ----
    question: str               # 用户提出的原始问题
    normalized_question: str    # preflight 规范化后的问题，用于 Studio/trace 排障
    request_mode: Literal["sync", "sse"]  # 当前请求入口，用于调试与 tracing 命名
    user_style_name: str        # 用户自定义的助手风格名称
    user_style_prompt: str      # 用户自定义的助手说话风格 / 角色提示词
    short_term_messages: list[dict[str, Any]]  # 当前会话最近几轮消息，作为短期记忆
    short_term_context: str     # 最近几轮消息格式化后的上下文摘要
    session_memory: SessionMemory        # 当前会话的中期摘要记忆
    session_memory_context: str          # 中期记忆格式化后的上下文摘要
    long_term_context: str      # 用户长期学习记忆与风格偏好的摘要
    model_name: str             # application 层解析出的当前生效模型

    # ---- 路由结果 ----
    route_decision: str          # 图级路径摘要，便于 Studio/LangSmith 快速定位实际流转
    learning_context: dict[str, Any]  # {mode, level, need_steps, need_examples}
    route: Literal[
        "fast",      # 极简单问题 / 元问题 / 寒暄，跳过检索和外部工具
        "explain",   # 普通教学讲解，不主动调用外部工具
        "rag",       # 需要当前 notebook / 资料库作为依据
        "agent",     # 明确需要外部搜索 / 工具 / 最新信息
    ]
    route_confidence: float
    route_reason: str
    contextual_question: str     # 如果是追问，基于近期上下文补全后的问题；否则等于 question
    notebook_policy: Literal[
        "skip",      # 不检索 notebook，直接讲解或轻量回答
        "optional",  # 可检索 notebook，但低相关时丢弃并改用通用知识
        "required",  # 用户希望优先参考 notebook，低相关时可转通用知识并标注
        "strict",    # 用户明确要求只依据 notebook，低相关时不能编造或混入外部结论
    ]
    notebook_required: bool     # notebook_policy == strict 的布尔别名，回答阶段的硬约束开关
    search_policy: Literal[
        "forbidden", # 禁止外部搜索
        "allowed",   # 允许模型在低置信/资料不足且问题需要外部事实时搜索
        "required",  # 时效、官网、来源类问题必须搜索
    ]
    external_search_required: bool # search_policy == required 的布尔别名，便于前端和回答阶段判断
    source_policy: Literal[
        "none",      # 不要求标注来源
        "notebook",  # 最终回答应依据并说明 notebook
        "web",       # 最终回答应依据外部搜索/网页资料
        "mixed",     # 同时使用 notebook 与 web
    ]
    answer_mode: Literal[
        "general_teaching",       # 普通教学讲解，不因 notebook 为空拒答
        "notebook_grounded",      # 严格依据通过审查的 notebook 内容
        "hybrid",                 # notebook 或 web 作为辅助，允许通用知识补充
        "insufficient_notebook",  # 用户要求 notebook 但资料不足
    ]
    source_usage: Literal[
        "none",
        "model",
        "notebook",
        "web",
        "mixed",
    ]
    reasoning_summary: str
    tool_decision_rounds: list[dict[str, Any]]
    question_type: Literal[
        "concept",   # 概念理解类
        "problem",   # 解题求助类
        "compare",   # 概念比较类
        "application", # 应用场景类
        "practice",  # 练习出题类
        "review",    # 复习巩固类
        "meta",      # 助手/模型/能力等元问题
        "smalltalk", # 寒暄 / 闲聊 / 开场白
        "mcq_problem", # 带选项的选择题求解
    ]

    # ---- 检索结果 ----
    raw_retrieved_docs: list[dict[str, Any]]
    # 原始检索命中，仅用于审查、调试和过程面板，不能直接进入最终回答。
    verified_context: list[dict[str, Any]]
    # 通过 Context Audit 的资料，后续回答和 fallback 唯一允许读取的 notebook context。
    context_audit: dict[str, Any]
    # {usable, score, reason, discarded_count, verified_count, decision, matched_terms, missing_terms, can_answer_question}
    retrieved_docs: list[dict[str, Any]]
    # 兼容字段，语义收敛为 verified_context；每个 doc: { "content": str, "metadata": dict, "score": float }
    notebook_retrieved: bool      # notebook 检索是否产生过原始命中，不代表可用于回答
    notebook_context: str         # verified_context 格式化后的可回答上下文；为空时不能读取 raw_retrieved_docs
    is_rewritten: bool              # 检索 Agent 是否重写了原始问题
    contextual_query: str           # 注入短期/长期记忆后用于检索分析的查询
    retrieval_diagnosis: dict[str, Any]
    rag_precomputed: bool            # 是否已由 LangGraph rag_node 完成预检索
    rag_ready: bool                  # 当前 RAG 命中质量是否足以支撑 notebook 问答
    rag_warning: str                 # RAG fail-open 或低质量命中的可读提示
    web_search_required: bool         # RAG 低命中时是否建议进入显式 Web Search 节点
    external_tool_calls: list[dict[str, Any]]  # 非模型 tool-calling 路径触发的外部工具观测，如 Tavily
    web_search_attempted: bool        # web_search_node 是否尝试过网络搜索回退
    web_search_used: bool             # 网络搜索结果是否被用于本轮上下文
    web_search_error: str             # 网络搜索失败的脱敏错误类型或状态
    web_search_diagnosis: dict[str, Any] # 网络搜索节点的脱敏诊断信息
    guard: dict[str, Any]                 # {allow_tools, allow_search, reason}
    allow_tools: bool
    allow_search: bool

    # ---- 讲解结果 ----
    explanation: Explanation

    # ---- 练习题 ----
    quiz_items: list[QuizItem]      # 出题 Agent 生成的练习题列表
    quiz_generation_status: QuizGenerationStatus
    quiz_plan: dict[str, Any]
    quiz_focus_points: list[str]    # 本轮出题优先覆盖的知识点
    quiz_target_difficulty: Literal["基础", "变式", "易错"]
    quiz_rag_docs: list[dict[str, Any]]
    quiz_rag_diagnosis: dict[str, Any]
    quiz_context: dict[str, Any]
    quiz_quality_report: dict[str, Any]
    quiz_retry_count: int

    # ---- 记忆 ----
    memory: Memory

    # ---- 最终回复（聚合后返回给前端） ----
    final_answer: str
    finalized: bool
    final_response_type: Literal["explanation", "quiz", "text", "error", "empty"]
    answer_guard_applied: bool
    answer_guard_reason: str

    # ---- 教学协议状态 ----
    teaching_input_type: Literal[
        "smalltalk",
        "problem",
        "concept",
        "compare",
        "application",
        "review",
        "check_answer",
    ]
    teaching_user_state: Literal[
        "first_contact",
        "fuzzy",
        "stuck",
        "practicing",
        "answer_wrong",
        "check_answer",
    ]
    teaching_knowledge_point: str
    pending_check: dict[str, Any]
    used_analogy: str
    stuck_count: int
    teaching_phase: str
    last_teaching_action: str
    teaching_waiting_for_user: bool
    knowledge_mastery: list[dict[str, Any]]
    code_execution_result: dict[str, Any]

    # ---- 主问答 runtime 调试信息 ----
    execution_mode: Literal["direct_answer", "tool_calling", "structured_output", "deterministic_context"]
    tool_calls: list[dict[str, Any]]
    degraded: bool
    selected_model_profile: dict[str, Any] | ModelProfile

    # ---- 图级观测与错误出口 ----
    graph_error: GraphError
    graph_warnings: Annotated[list[str], add]
    node_timings: Annotated[list[NodeTiming], add]
    graph_performance_summary: GraphPerformanceSummary
