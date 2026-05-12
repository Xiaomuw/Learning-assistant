"""create legacy core app tables required by readiness

Revision ID: 0012_core_app_tables
Revises: 0011_practice_finalizer
Create Date: 2026-05-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0012_core_app_tables"
down_revision: str | None = "0011_practice_finalizer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON_TYPE = sa.JSON()


def upgrade() -> None:
    _create_subjects_table()
    _create_chat_sessions_table()
    _create_question_bank_items_table()
    _create_practice_attempts_table()
    _create_user_knowledge_stats_table()
    _create_app_settings_table()
    _create_indexes()
    _create_foreign_keys()


def downgrade() -> None:
    for table_name in (
        "app_settings",
        "practice_attempts",
        "question_bank_items",
        "chat_sessions",
        "user_knowledge_stats",
        "subjects",
    ):
        if table_name in _tables():
            op.drop_table(table_name)


def _create_subjects_table() -> None:
    if "subjects" in _tables():
        return
    op.create_table(
        "subjects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(16), nullable=False, server_default="📚"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def _create_chat_sessions_table() -> None:
    if "chat_sessions" in _tables():
        return
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False, server_default="general"),
        sa.Column("title", sa.String(120), nullable=False, server_default="新对话"),
        sa.Column("messages", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("latest_quiz", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("session_memory", JSON_TYPE, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def _create_question_bank_items_table() -> None:
    if "question_bank_items" in _tables():
        return
    op.create_table(
        "question_bank_items",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("subject_id", sa.String(64), nullable=False, server_default="general"),
        sa.Column("knowledge_point", sa.String(120), nullable=False, server_default=""),
        sa.Column("chapter_id", sa.String(160), nullable=True, server_default=""),
        sa.Column("topic_id", sa.String(180), nullable=True, server_default=""),
        sa.Column("concept_id", sa.String(200), nullable=True, server_default=""),
        sa.Column("concept_name", sa.String(240), nullable=True, server_default=""),
        sa.Column("concept_mapping_status", sa.String(30), nullable=True, server_default=""),
        sa.Column("stem", sa.Text(), nullable=False, server_default=""),
        sa.Column("options_json", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("correct_option", sa.String(1), nullable=False, server_default="A"),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("option_rationales_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("source_year", sa.Integer(), nullable=True),
        sa.Column("difficulty", sa.String(20), nullable=False, server_default="基础"),
        sa.Column("tags_json", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def _create_practice_attempts_table() -> None:
    if "practice_attempts" in _tables():
        return
    op.create_table(
        "practice_attempts",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("session_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("subject_id", sa.String(64), nullable=False, server_default="general"),
        sa.Column("question_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("question_snapshot", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("selected_option", sa.String(1), nullable=False, server_default=""),
        sa.Column("is_correct", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("knowledge_point", sa.String(120), nullable=False, server_default=""),
        sa.Column("chapter_id", sa.String(160), nullable=True, server_default=""),
        sa.Column("topic_id", sa.String(180), nullable=True, server_default=""),
        sa.Column("concept_id", sa.String(200), nullable=True, server_default=""),
        sa.Column("concept_name", sa.String(240), nullable=True, server_default=""),
        sa.Column("concept_mapping_status", sa.String(30), nullable=True, server_default=""),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="ai_generated"),
        sa.Column("idempotency_key", sa.String(160), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def _create_user_knowledge_stats_table() -> None:
    if "user_knowledge_stats" in _tables():
        return
    op.create_table(
        "user_knowledge_stats",
        sa.Column("user_id", sa.String(100), primary_key=True),
        sa.Column("subject_id", sa.String(64), primary_key=True, server_default="general"),
        sa.Column("knowledge_point", sa.String(160), primary_key=True),
        sa.Column("chapter_id", sa.String(160), nullable=True, server_default=""),
        sa.Column("topic_id", sa.String(180), nullable=True, server_default=""),
        sa.Column("concept_id", sa.String(200), nullable=True, server_default=""),
        sa.Column("concept_name", sa.String(240), nullable=True, server_default=""),
        sa.Column("concept_mapping_status", sa.String(30), nullable=True, server_default=""),
        sa.Column("exposure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mastery_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mastery_level", sa.String(20), nullable=False, server_default="weak"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_practiced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def _create_app_settings_table() -> None:
    if "app_settings" in _tables():
        return
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def _create_indexes() -> None:
    _create_index("ix_subjects_name", "subjects", ["name"], unique=True)
    _create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    _create_index("ix_chat_sessions_subject_id", "chat_sessions", ["subject_id"])
    _create_index("idx_chat_sessions_user_updated", "chat_sessions", ["user_id", "updated_at"])
    _create_index("ix_question_bank_items_subject_id", "question_bank_items", ["subject_id"])
    _create_index("ix_question_bank_items_knowledge_point", "question_bank_items", ["knowledge_point"])
    _create_index("ix_question_bank_items_concept_id", "question_bank_items", ["concept_id"])
    _create_index("ix_practice_attempts_user_id", "practice_attempts", ["user_id"])
    _create_index("ix_practice_attempts_session_id", "practice_attempts", ["session_id"])
    _create_index("ix_practice_attempts_subject_id", "practice_attempts", ["subject_id"])
    _create_index("ix_practice_attempts_knowledge_point", "practice_attempts", ["knowledge_point"])
    _create_index("ix_practice_attempts_concept_id", "practice_attempts", ["concept_id"])
    _create_index("idx_practice_attempts_user_created", "practice_attempts", ["user_id", "created_at"])
    _create_index(
        "uq_practice_attempts_idempotency_key",
        "practice_attempts",
        ["idempotency_key"],
        unique=True,
        where="idempotency_key IS NOT NULL AND idempotency_key <> ''",
    )
    _create_index("ix_user_knowledge_stats_concept_id", "user_knowledge_stats", ["concept_id"])
    _create_index("idx_user_knowledge_stats_user_concept", "user_knowledge_stats", ["user_id", "concept_id"])


def _create_foreign_keys() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    _create_not_valid_foreign_key("fk_chat_sessions_user", "chat_sessions", ["user_id"], "users", ["id"], ondelete="CASCADE")
    _create_not_valid_foreign_key("fk_practice_attempts_user", "practice_attempts", ["user_id"], "users", ["id"], ondelete="CASCADE")
    _create_not_valid_foreign_key(
        "fk_user_knowledge_stats_user",
        "user_knowledge_stats",
        ["user_id"],
        "users",
        ["id"],
        ondelete="CASCADE",
    )


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_index(
    name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
    where: str | None = None,
) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return
    table_columns = {item["name"] for item in inspector.get_columns(table_name)}
    if not set(columns).issubset(table_columns):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name in existing:
        return
    kwargs: dict[str, object] = {"unique": unique}
    if where and bind.dialect.name == "postgresql":
        kwargs["postgresql_where"] = sa.text(where)
    if where and bind.dialect.name == "sqlite":
        kwargs["sqlite_where"] = sa.text(where)
    op.create_index(name, table_name, columns, **kwargs)


def _create_not_valid_foreign_key(
    name: str,
    source_table: str,
    local_cols: list[str],
    referent_table: str,
    remote_cols: list[str],
    *,
    ondelete: str | None,
) -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if source_table not in tables or referent_table not in tables:
        return
    source_columns = {item["name"] for item in inspector.get_columns(source_table)}
    referent_columns = {item["name"] for item in inspector.get_columns(referent_table)}
    if not set(local_cols).issubset(source_columns) or not set(remote_cols).issubset(referent_columns):
        return
    existing = {item["name"] for item in inspector.get_foreign_keys(source_table)}
    if name in existing:
        return
    op.create_foreign_key(
        name,
        source_table,
        referent_table,
        local_cols,
        remote_cols,
        ondelete=ondelete,
        postgresql_not_valid=True,
    )
