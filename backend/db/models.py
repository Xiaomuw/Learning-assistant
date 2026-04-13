"""
数据库模型
==========
"""

from __future__ import annotations

from sqlalchemy import DateTime, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base


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


class UserMemoryModel(Base):
    __tablename__ = "user_memories"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    weak_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error_count: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recent_topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_session: Mapped[str] = mapped_column(String(200), nullable=False, default="")
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


class ChatSessionModel(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="general")
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="新对话")
    messages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    latest_quiz: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
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
