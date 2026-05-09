"""
内部强类型契约
==============
为 application / repositories / services 之间提供稳定的数据契约。
对外 API 仍保持现有 JSON 结构，由 interfaces 层完成转换。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.shared.schemas.subject import DEFAULT_SUBJECT_ID


class SubjectRecord(BaseModel):
    id: str
    name: str
    icon: str
    description: str = ""
    doc_count: int = 0
    created_at: str = ""


class NotebookListItem(SubjectRecord):
    """应用层默认使用的笔记本列表项契约。"""


class NotebookKnowledgeGenerationResult(BaseModel):
    subject_id: str
    subject_name: str
    chapters: int
    total_chunks: int
    chapter_titles: list[str] = Field(default_factory=list)
    message: str


class NotebookKnowledgeStatus(BaseModel):
    subject_id: str
    collection_name: str
    doc_count: int = 0
    shared_doc_count: int = 0
    personal_doc_count: int = 0
    chapter_count: int = 0
    exam_pattern_count: int = 0
    question_count: int = 0
    url_count: int = 0
    pdf_count: int = 0
    personal_pdf_count: int = 0
    personal_url_count: int = 0
    personal_ready: bool = False
    embedding_ready: bool = False
    schema_ready: bool = False
    index_ready: bool = False
    schema_issues: list[str] = Field(default_factory=list)
    embedding_profile: dict[str, Any] = Field(default_factory=dict)
    coverage_score: int = 0
    coverage_level: Literal["empty", "sparse", "partial", "ready"] = "empty"
    missing_doc_types: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    retrieval_ready: bool = False


class DeleteResult(BaseModel):
    message: str


class MessageResult(BaseModel):
    message: str


class IngestResult(BaseModel):
    subject_id: str
    total_chunks: int
    message: str
    mapped_chunks: int = 0
    unmapped_chunks: int = 0
    filename: str = ""
    total_pages: int = 0
    total_urls: int = 0
    successful_urls: int = 0


class RetrievedDocument(BaseModel):
    doc_id: str = ""
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    distance: float = 0.0


class RetrievalDiagnostics(BaseModel):
    query: str = ""
    hit_count: int = 0
    top_score: float = 0.0
    raw_hit_count: int = 0
    raw_top_score: float = 0.0
    verified_count: int = 0
    filter_reason: str = ""
    retrieval_stage: str = ""
    used_keyword_fallback: bool = False
    filters: dict[str, Any] = Field(default_factory=dict)
    doc_type_counts: dict[str, int] = Field(default_factory=dict)
    diagnosis: Literal[
        "empty_knowledge_base",
        "low_score",
        "no_matching_docs",
        "ready",
    ] = "empty_knowledge_base"
    coverage_level: Literal["empty", "sparse", "partial", "ready"] = "empty"
    suggested_actions: list[str] = Field(default_factory=list)


class PendingCheckState(BaseModel):
    """当前会话中等待用户回答的教学检查点。"""

    knowledge_point: str = ""
    prompt: str = ""
    expected_keywords: list[str] = Field(default_factory=list)
    teaching_input_type: str = "concept"
    attempts: int = 0


class CodeExecutionResult(BaseModel):
    """受限代码/计算验证结果。"""

    executed: bool = False
    language: str = ""
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    hint: str = ""
    blocked: bool = False
    timed_out: bool = False


class TeachingPolicyDecision(BaseModel):
    """教学策略层对本轮输入的决策。"""

    teaching_input_type: Literal[
        "smalltalk",
        "problem",
        "concept",
        "compare",
        "application",
        "review",
        "check_answer",
    ] = "concept"
    teaching_user_state: Literal[
        "first_contact",
        "fuzzy",
        "stuck",
        "practicing",
        "answer_wrong",
        "check_answer",
    ] = "first_contact"
    knowledge_point: str = ""
    used_analogy: str = ""
    pending_check: PendingCheckState | None = None
    stuck_count: int = 0
    mastery_score: float | None = None
    should_wait_for_user: bool = False
    last_teaching_action: str = ""


class UserMemoryRecord(BaseModel):
    weak_points: list[str] = Field(default_factory=list)
    error_count: dict[str, int] = Field(default_factory=dict)
    recent_topics: list[str] = Field(default_factory=list)
    last_session: str = ""


class KnowledgeMasteryRecord(BaseModel):
    user_id: str
    subject_id: str = DEFAULT_SUBJECT_ID
    knowledge_point: str
    chapter_id: str = ""
    topic_id: str = ""
    concept_id: str = ""
    concept_name: str = ""
    concept_mapping_status: str = ""
    exposure_count: int = 0
    attempt_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    mastery_score: float = 0.0
    mastery_level: str = "weak"
    last_seen_at: str = ""
    last_practiced_at: str = ""
    updated_at: str = ""


class KnowledgeMasteryResult(BaseModel):
    user_id: str
    subject_id: str | None = None
    items: list[KnowledgeMasteryRecord] = Field(default_factory=list)


class LearningCenterConcept(BaseModel):
    concept_id: str
    concept_name: str
    subject_id: str
    chapter_id: str = ""
    topic_id: str = ""
    aliases: list[str] = Field(default_factory=list)
    importance: Literal["high", "medium", "low"] = "medium"
    exam_frequency: Literal["high", "medium", "low"] = "medium"
    prerequisites: list[str] = Field(default_factory=list)
    p_mastery: float = 0.0
    mastery_score: float = 0.0
    coverage_ratio: float = 0.0
    status: Literal["unstarted", "weak", "learning", "mastered"] = "unstarted"
    status_counts: dict[str, int] = Field(default_factory=dict)
    weak_count: int = 0
    tested: bool = False
    test_status: Literal["untested", "tested"] = "untested"
    attempt_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    question_count: int = 0
    last_practiced_at: str = ""
    updated_at: str = ""


class LearningCenterTopic(BaseModel):
    topic_id: str
    topic_name: str
    subject_id: str
    chapter_id: str
    mastery_score: float = 0.0
    coverage_ratio: float = 0.0
    status_counts: dict[str, int] = Field(default_factory=dict)
    weak_count: int = 0
    tested_count: int = 0
    untested_count: int = 0
    tested_ratio: float = 0.0
    attempt_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    updated_at: str = ""
    concepts: list[LearningCenterConcept] = Field(default_factory=list)


class LearningCenterChapter(BaseModel):
    chapter_id: str
    chapter_name: str
    subject_id: str
    mastery_score: float = 0.0
    coverage_ratio: float = 0.0
    status_counts: dict[str, int] = Field(default_factory=dict)
    weak_count: int = 0
    tested_count: int = 0
    untested_count: int = 0
    tested_ratio: float = 0.0
    attempt_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    updated_at: str = ""
    topics: list[LearningCenterTopic] = Field(default_factory=list)


class LearningCenterSubject(BaseModel):
    subject_id: str
    subject_name: str
    mastery_score: float = 0.0
    coverage_ratio: float = 0.0
    status_counts: dict[str, int] = Field(default_factory=dict)
    weak_count: int = 0
    tested_count: int = 0
    untested_count: int = 0
    tested_ratio: float = 0.0
    attempt_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    updated_at: str = ""
    chapters: list[LearningCenterChapter] = Field(default_factory=list)


class LearningCenterNextMove(BaseModel):
    concept_id: str = ""
    concept_name: str = ""
    subject_id: str = ""
    chapter_id: str = ""
    topic_id: str = ""
    action: Literal["review_weak", "practice_learning", "start_high_value", "none"] = "none"
    reason: str = ""


class LearningCenterResponse(BaseModel):
    user_id: str
    subject_id: str | None = None
    subjects: list[LearningCenterSubject] = Field(default_factory=list)
    next_move: LearningCenterNextMove | None = None


class AnswerNormalizationResult(BaseModel):
    answer_type: Literal["mcq", "blank", "short_answer"] = "mcq"
    normalized_answer: str = ""
    is_valid: bool = True
    issues: list[str] = Field(default_factory=list)


class MasteryScoreBreakdown(BaseModel):
    accuracy: float = 0.0
    completeness: float = 0.0
    understanding_depth: float = 0.0
    confidence: float = 0.0
    rag_doc_count: int = 0
    low_confidence: bool = False
    issues: list[str] = Field(default_factory=list)


class MasteryEvaluationResult(BaseModel):
    subject_id: str = DEFAULT_SUBJECT_ID
    knowledge_point: str = "综合"
    chapter_id: str = ""
    topic_id: str = ""
    concept_id: str = ""
    concept_name: str = ""
    concept_mapping_status: str = ""
    answer_type: Literal["mcq", "blank", "short_answer"] = "mcq"
    normalized_answer: str = ""
    is_correct: bool = False
    score: float = 0.0
    mastery_score: float = 0.0
    mastery_level: str = "weak"
    weak_points: list[str] = Field(default_factory=list)
    feedback: str = ""
    score_breakdown: MasteryScoreBreakdown = Field(default_factory=MasteryScoreBreakdown)
    retrieval_diagnosis: str = ""
    reference_doc_count: int = 0


class UserProfileRecord(BaseModel):
    user_id: str
    display_name: str = ""
    agent_style_name: str = ""
    agent_style_prompt: str = ""
    onboarding_completed: bool = False


class AuthUserView(BaseModel):
    id: str
    email: str
    display_name: str = ""
    status: str = "active"
    last_login_at: str = ""


class AuthSessionResult(BaseModel):
    user: AuthUserView
    access_token: str
    refresh_token: str


class VerificationDispatchResult(BaseModel):
    message: str
    expires_in_seconds: int
    resend_after_seconds: int


class AuthUserRecord(AuthUserView):
    """兼容保留：等价于 AuthUserView。"""


class AuthUserCredentialsRecord(BaseModel):
    id: str
    email: str
    password_hash: str
    status: str = "active"
    last_login_at: str = ""


class RefreshTokenRecord(BaseModel):
    id: str
    user_id: str
    token_jti: str
    token_hash: str
    expires_at: Any = None
    revoked_at: Any = None
    created_at: Any = None
    last_used_at: Any = None


class EmailVerificationChallengeRecord(BaseModel):
    id: str
    email: str
    purpose: str = "register"
    code_hash: str
    expires_at: Any = None
    attempt_count: int = 0
    max_attempts: int = 5
    verified_at: Any = None
    consumed_at: Any = None
    last_sent_at: Any = None
    created_at: Any = None
    updated_at: Any = None


class ChatSessionRecord(BaseModel):
    id: str
    user_id: str
    subject_id: str = DEFAULT_SUBJECT_ID
    title: str = "新对话"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    latest_quiz: list[dict[str, Any]] = Field(default_factory=list)
    session_memory: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class QuestionBankItemRecord(BaseModel):
    id: str
    question_id: str
    subject_id: str = DEFAULT_SUBJECT_ID
    knowledge_point: str = ""
    chapter_id: str = ""
    topic_id: str = ""
    concept_id: str = ""
    concept_name: str = ""
    concept_mapping_status: str = ""
    question: str = ""
    options: list[dict[str, str]] = Field(default_factory=list)
    correct_option: str = "A"
    explanation: str = ""
    option_rationales: dict[str, str] = Field(default_factory=dict)
    difficulty: str = "基础"
    source_type: str = "question_bank"
    source_name: str = ""
    source_year: int | None = None
    hint: str = ""
    tags: list[str] = Field(default_factory=list)


class PracticeRecommendation(BaseModel):
    question_id: str
    question: str
    options: list[dict[str, str]] = Field(default_factory=list)
    correct_option: str = "A"
    explanation: str = ""
    option_rationales: dict[str, str] = Field(default_factory=dict)
    knowledge_point: str = ""
    chapter_id: str = ""
    topic_id: str = ""
    concept_id: str = ""
    concept_name: str = ""
    concept_mapping_status: str = ""
    difficulty: str = "基础"
    source_type: str = "ai_generated"
    source_name: str = ""
    source_year: int | None = None
    hint: str = ""


class QuizRecommendedOption(BaseModel):
    label: str
    value: str
    source: Literal["recent_topic", "weak_point", "default", "current_context"] = "default"


class QuizRequestResolution(BaseModel):
    is_quiz_request: bool = False
    action: Literal[
        "generate_practice_pack",
        "clarify_quiz_request",
        "continue_practice",
        "normal_qa",
    ] = "normal_qa"
    intent: Literal[
        "quiz_generation",
        "continue_quiz_generation",
        "quiz_answer_check",
        "normal_qa",
    ] = "normal_qa"
    topic: str | None = None
    subject_id: str | None = None
    source: Literal[
        "explicit_user_input",
        "current_question",
        "last_topic",
        "recent_topic",
        "weak_point",
        "unknown",
    ] = "unknown"
    question_type: Literal[
        "single_choice",
        "multiple_choice",
        "true_false",
        "short_answer",
        "mixed",
        "unknown",
    ] = "single_choice"
    difficulty: Literal["easy", "medium", "hard", "adaptive", "unknown"] = "adaptive"
    count: int | None = Field(default=5, ge=1, le=10)
    requested_topic: str | None = None
    previous_topic: str | None = None
    active_topic: str | None = None
    should_switch_topic: bool = False
    topic_resolution_reason: str = ""
    target_module: Literal["practice", "qa"] = "qa"
    need_clarification: bool = False
    clarification_reason: str | None = None
    recommended_options: list[QuizRecommendedOption] = Field(default_factory=list)
    custom_input_placeholder: str | None = None
    reason: str = ""


class QuizClarificationPanel(BaseModel):
    title: str = "想练哪一块？"
    description: str = "我可以帮你生成练习题，但需要先确定练习方向。"
    recommended_options: list[QuizRecommendedOption] = Field(default_factory=list)
    question_type_options: list[QuizRecommendedOption] = Field(default_factory=list)
    difficulty_options: list[QuizRecommendedOption] = Field(default_factory=list)
    count_options: list[QuizRecommendedOption] = Field(default_factory=list)
    custom_input_placeholder: str = "例如：围绕 HashMap 出 5 道单选题"


class PracticePackResult(BaseModel):
    subject_id: str = DEFAULT_SUBJECT_ID
    quiz_request: QuizRequestResolution
    quiz_clarification: QuizClarificationPanel | None = None
    items: list[PracticeRecommendation] = Field(default_factory=list)
    generation_status: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    message: str = ""


class QuizPlan(BaseModel):
    focus_points: list[str] = Field(default_factory=list)
    target_difficulty: str = "基础"
    mastery_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "question"


class QuizGenerationContext(BaseModel):
    subject_id: str = DEFAULT_SUBJECT_ID
    subject_name: str = "综合"
    topic: str = "综合"
    difficulty: str = "基础"
    focus_points: list[str] = Field(default_factory=list)
    rag_context: str = ""
    mastery_summary: str = ""
    retry_count: int = 0
    requested_count: int = 2


class QuizQualityReport(BaseModel):
    passed: bool = False
    issues: list[str] = Field(default_factory=list)
    checked_count: int = 0
    expected_count: int = 0
    retry_recommended: bool = False


class PracticeAttemptRecord(BaseModel):
    id: str
    user_id: str
    session_id: str = ""
    subject_id: str = DEFAULT_SUBJECT_ID
    question_id: str = ""
    question_snapshot: dict[str, Any] = Field(default_factory=dict)
    selected_option: str = ""
    is_correct: bool = False
    knowledge_point: str = ""
    chapter_id: str = ""
    topic_id: str = ""
    concept_id: str = ""
    concept_name: str = ""
    concept_mapping_status: str = ""
    source_type: str = "ai_generated"
    created_at: str = ""


class AppSettingRecord(BaseModel):
    key: str
    value: str


class PracticeRecommendationsResult(BaseModel):
    subject_id: str = DEFAULT_SUBJECT_ID
    items: list[PracticeRecommendation] = Field(default_factory=list)


class PracticeSubmissionResult(BaseModel):
    is_correct: bool
    selected_option: str = ""
    correct_option: str
    explanation: str
    option_rationales: dict[str, str] = Field(default_factory=dict)
    memory: UserMemoryRecord
    session_memory: dict[str, Any] | None = None
    mastery_evaluation: MasteryEvaluationResult | None = None
    personalized_feedback: str = ""


class ModelOptionRecord(BaseModel):
    id: str
    label: str
    provider: str
    family: str


class ModelConfigSnapshot(BaseModel):
    current_model: str
    embedding_model: str
    available_models: list[ModelOptionRecord] = Field(default_factory=list)
    model_switching_enabled: bool = False
    model_switching_status: str = "development"
    locked_model: str = "openai-gpt-4.1"


class LatestQuizBundle(BaseModel):
    session_id: str = ""
    subject_id: str = DEFAULT_SUBJECT_ID
    quiz_items: list[dict[str, Any]] = Field(default_factory=list)


class ExplanationPayload(BaseModel):
    topic: str = ""
    thinking: str = ""
    steps: list[str] = Field(default_factory=list)
    mistakes: str = ""
    similar: list[str] = Field(default_factory=list)


class ChatExecutionResult(BaseModel):
    session_id: str
    question_type: str = "concept"
    route: str = "explain"
    explanation: ExplanationPayload = Field(default_factory=ExplanationPayload)
    quiz_items: list[PracticeRecommendation] = Field(default_factory=list)
    quiz_request: QuizRequestResolution | None = None
    quiz_clarification: QuizClarificationPanel | None = None
    memory: UserMemoryRecord = Field(default_factory=UserMemoryRecord)
