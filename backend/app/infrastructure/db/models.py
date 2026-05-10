"""
数据库模型
==========
"""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.database import Base


GraphJSON = JSONB().with_variant(JSON(), "sqlite")


class SubjectModel(Base):
    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="📚")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class KbSubjectModel(Base):
    __tablename__ = "kb_subject"

    subject_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class KbChapterModel(Base):
    __tablename__ = "kb_chapter"

    chapter_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    chapter_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class KbTopicModel(Base):
    __tablename__ = "kb_topic"

    topic_id: Mapped[str] = mapped_column(String(180), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    chapter_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    topic_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class KbConceptModel(Base):
    __tablename__ = "kb_concept"

    concept_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    chapter_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    topic_id: Mapped[str] = mapped_column(String(180), index=True, nullable=False)
    concept_name: Mapped[str] = mapped_column(String(240), index=True, nullable=False, default="")
    aliases_json: Mapped[list] = mapped_column(GraphJSON, nullable=False, default=list)
    prerequisites_json: Mapped[list] = mapped_column(GraphJSON, nullable=False, default=list)
    importance: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    exam_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    question_types_json: Mapped[list] = mapped_column(GraphJSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class KbChunkModel(Base):
    __tablename__ = "kb_chunk"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    vector_id: Mapped[str] = mapped_column(String(240), index=True, nullable=False, default="")
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")
    subject_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    chapter_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False, default="")
    chapter_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    topic_id: Mapped[str] = mapped_column(String(180), index=True, nullable=False, default="")
    topic_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    concept_id: Mapped[str] = mapped_column(String(200), index=True, nullable=False, default="")
    concept_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    source_file: Mapped[str] = mapped_column(String(500), index=True, nullable=False, default="")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    mapping_status: Mapped[str] = mapped_column(String(30), index=True, nullable=False, default="unmapped")
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_kb_chunk_subject_concept", "subject_id", "concept_id"),
        Index("idx_kb_chunk_source_status", "source_file", "mapping_status"),
    )


class UserMemoryModel(Base):
    __tablename__ = "user_memories"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    weak_points: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error_count: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    recent_topics: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    last_session: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserKnowledgeStatModel(Base):
    __tablename__ = "user_knowledge_stats"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="general")
    knowledge_point: Mapped[str] = mapped_column(String(160), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String(160), nullable=True, default="")
    topic_id: Mapped[str] = mapped_column(String(180), nullable=True, default="")
    concept_id: Mapped[str] = mapped_column(String(200), index=True, nullable=True, default="")
    concept_name: Mapped[str] = mapped_column(String(240), nullable=True, default="")
    concept_mapping_status: Mapped[str] = mapped_column(String(30), nullable=True, default="")
    exposure_count: Mapped[int] = mapped_column(nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(nullable=False, default=0)
    mastery_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mastery_level: Mapped[str] = mapped_column(String(20), nullable=False, default="weak")
    last_seen_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    last_practiced_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserProfileModel(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    agent_style_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    agent_style_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    onboarding_completed: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class AuthRefreshTokenModel(Base):
    __tablename__ = "auth_refresh_tokens"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    token_jti: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class WechatMiniIdentityModel(Base):
    __tablename__ = "wechat_mini_identities"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    openid: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    unionid: Mapped[str] = mapped_column(String(128), index=True, nullable=False, default="")
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class EmailVerificationChallengeModel(Base):
    __tablename__ = "email_verification_challenges"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), index=True, nullable=False, default="register")
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=5)
    verified_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    consumed_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    last_sent_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ChatSessionModel(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="general")
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="新对话")
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    latest_quiz: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    session_memory: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class QuestionBankItemModel(Base):
    __tablename__ = "question_bank_items"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="general")
    knowledge_point: Mapped[str] = mapped_column(String(120), index=True, nullable=False, default="")
    chapter_id: Mapped[str] = mapped_column(String(160), nullable=True, default="")
    topic_id: Mapped[str] = mapped_column(String(180), nullable=True, default="")
    concept_id: Mapped[str] = mapped_column(String(200), index=True, nullable=True, default="")
    concept_name: Mapped[str] = mapped_column(String(240), nullable=True, default="")
    concept_mapping_status: Mapped[str] = mapped_column(String(30), nullable=True, default="")
    stem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    correct_option: Mapped[str] = mapped_column(String(1), nullable=False, default="A")
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    option_rationales_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    source_year: Mapped[int | None] = mapped_column(nullable=True, default=None)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, default="基础")
    tags_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PracticeQuestionModel(Base):
    __tablename__ = "practice_question"

    question_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")
    subject_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    chapter_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    topic_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    concept_id: Mapped[str] = mapped_column(String(200), index=True, nullable=False, default="")
    concept_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    difficulty: Mapped[str] = mapped_column(String(20), index=True, nullable=False, default="medium")
    stem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    answer: Mapped[str] = mapped_column(String(1), nullable=False, default="A")
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    knowledge_points_json: Mapped[list] = mapped_column(GraphJSON, nullable=False, default=list)
    common_trap: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    source_file: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PracticeAttemptModel(Base):
    __tablename__ = "practice_attempts"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="general")
    question_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    question_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    selected_option: Mapped[str] = mapped_column(String(1), nullable=False, default="")
    is_correct: Mapped[bool] = mapped_column(nullable=False, default=False)
    knowledge_point: Mapped[str] = mapped_column(String(120), index=True, nullable=False, default="")
    chapter_id: Mapped[str] = mapped_column(String(160), nullable=True, default="")
    topic_id: Mapped[str] = mapped_column(String(180), nullable=True, default="")
    concept_id: Mapped[str] = mapped_column(String(200), index=True, nullable=True, default="")
    concept_name: Mapped[str] = mapped_column(String(240), nullable=True, default="")
    concept_mapping_status: Mapped[str] = mapped_column(String(30), nullable=True, default="")
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="ai_generated")
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AppSettingModel(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class GraphRunModel(Base):
    __tablename__ = "graph_runs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    graph_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="")
    graph_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    run_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False, default="running")
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    session_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="general")
    notebook_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    source_policy: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    request_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    langsmith_run_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False, default="")
    sampled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    inputs_summary: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    outputs_summary: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ended_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class NodeRunModel(Base):
    __tablename__ = "node_runs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    graph_run_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    node_name: Mapped[str] = mapped_column(String(120), index=True, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")
    input_summary: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    output_summary: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ended_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class ToolRunModel(Base):
    __tablename__ = "tool_runs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    graph_run_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    tool_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="")
    capability: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), index=True, nullable=False, default="")
    input_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_summary: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    evidence_refs: Mapped[list] = mapped_column(GraphJSON, nullable=False, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LearningEventModel(Base):
    __tablename__ = "learning_events"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    concept_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True, default=None)
    graph_run_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    hash_key: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True, default=None)
    payload: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_learning_events_user_created", "user_id", "created_at"),
        Index(
            "uq_learning_events_hash_key",
            "hash_key",
            unique=True,
            postgresql_where=text("hash_key IS NOT NULL AND hash_key <> ''"),
            sqlite_where=text("hash_key IS NOT NULL AND hash_key <> ''"),
        ),
    )


class GraphAttemptModel(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="general")
    concept_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False, default="")
    question_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    graph_run_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    source_event_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    score: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    payload: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MasterySnapshotModel(Base):
    __tablename__ = "mastery_snapshots"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="general")
    concept_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    p_mastery: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="learning")
    evidence_ids: Mapped[list] = mapped_column(GraphJSON, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "subject_id", "concept_id", name="uq_mastery_snapshots_user_subject_concept"),
        Index("idx_mastery_snapshots_user_updated", "user_id", "updated_at"),
    )


class GraphQuestionItemModel(Base):
    __tablename__ = "question_items"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="general")
    primary_concept_id: Mapped[str] = mapped_column(String(160), index=True, nullable=False, default="")
    graph_run_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False, default="")
    stem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options_json: Mapped[list] = mapped_column(GraphJSON, nullable=False, default=list)
    difficulty: Mapped[str] = mapped_column(String(30), nullable=False, default="基础")
    source_refs: Mapped[list] = mapped_column(GraphJSON, nullable=False, default=list)
    answer_key: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    rubric: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    quality_report: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    generation_source: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_question_items_subject_concept", "subject_id", "primary_concept_id"),
    )


class GraphConceptModel(Base):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(240), unique=True, index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="general")
    aliases: Mapped[list] = mapped_column(GraphJSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="graph")
    metadata_json: Mapped[dict] = mapped_column(GraphJSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
