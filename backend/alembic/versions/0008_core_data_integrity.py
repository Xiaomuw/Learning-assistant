"""add core data integrity constraints and maintenance indexes

Revision ID: 0008_core_data_integrity
Revises: 0007_learning_event_idempotency
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_core_data_integrity"
down_revision: str | None = "0007_learning_event_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_SPECS: tuple[tuple[str, str, list[str]], ...] = (
    ("idx_kb_concept_subject_chapter_topic", "kb_concept", ["subject_id", "chapter_id", "topic_id"]),
    ("idx_kb_topic_subject_chapter", "kb_topic", ["subject_id", "chapter_id"]),
    ("idx_practice_question_subject_concept", "practice_question", ["subject_id", "concept_id"]),
    ("idx_practice_question_concept_difficulty", "practice_question", ["concept_id", "difficulty"]),
    ("idx_auth_refresh_tokens_user_expires", "auth_refresh_tokens", ["user_id", "expires_at"]),
    ("idx_auth_refresh_tokens_revoked_expires", "auth_refresh_tokens", ["revoked_at", "expires_at"]),
    ("idx_email_verification_challenges_cleanup", "email_verification_challenges", ["expires_at", "consumed_at"]),
    # Graph-era fact tables keep indexes for audit/query speed, but their referential
    # integrity stays soft for now because they may contain imported legacy facts.
    ("idx_graph_runs_user_created", "graph_runs", ["user_id", "created_at"]),
    ("idx_learning_events_user_graph_run", "learning_events", ["user_id", "graph_run_id"]),
    ("idx_attempts_user_concept_created", "attempts", ["user_id", "concept_id", "created_at"]),
    ("idx_mastery_snapshots_user_concept_updated", "mastery_snapshots", ["user_id", "concept_id", "updated_at"]),
    ("idx_question_items_user_concept", "question_items", ["user_id", "primary_concept_id"]),
    ("idx_chat_sessions_user_updated", "chat_sessions", ["user_id", "updated_at"]),
    ("idx_practice_attempts_user_created", "practice_attempts", ["user_id", "created_at"]),
    ("idx_user_knowledge_stats_user_concept", "user_knowledge_stats", ["user_id", "concept_id"]),
)


FK_SPECS: tuple[tuple[str, str, list[str], str, list[str], str | None], ...] = (
    ("fk_kb_chapter_subject", "kb_chapter", ["subject_id"], "kb_subject", ["subject_id"], None),
    ("fk_kb_topic_subject", "kb_topic", ["subject_id"], "kb_subject", ["subject_id"], None),
    ("fk_kb_topic_chapter", "kb_topic", ["chapter_id"], "kb_chapter", ["chapter_id"], None),
    ("fk_kb_concept_subject", "kb_concept", ["subject_id"], "kb_subject", ["subject_id"], None),
    ("fk_kb_concept_chapter", "kb_concept", ["chapter_id"], "kb_chapter", ["chapter_id"], None),
    ("fk_kb_concept_topic", "kb_concept", ["topic_id"], "kb_topic", ["topic_id"], None),
    ("fk_practice_question_subject", "practice_question", ["subject_id"], "kb_subject", ["subject_id"], None),
    (
        "fk_practice_question_concept_kb_concept",
        "practice_question",
        ["concept_id"],
        "kb_concept",
        ["concept_id"],
        None,
    ),
    ("fk_user_profiles_user", "user_profiles", ["user_id"], "users", ["id"], "CASCADE"),
    ("fk_user_memories_user", "user_memories", ["user_id"], "users", ["id"], "CASCADE"),
    ("fk_auth_refresh_tokens_user", "auth_refresh_tokens", ["user_id"], "users", ["id"], "CASCADE"),
    ("fk_wechat_mini_identities_user", "wechat_mini_identities", ["user_id"], "users", ["id"], "CASCADE"),
    ("fk_chat_sessions_user", "chat_sessions", ["user_id"], "users", ["id"], "CASCADE"),
    ("fk_practice_attempts_user", "practice_attempts", ["user_id"], "users", ["id"], "CASCADE"),
    ("fk_user_knowledge_stats_user", "user_knowledge_stats", ["user_id"], "users", ["id"], "CASCADE"),
)


def upgrade() -> None:
    _create_indexes()

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for name, source_table, local_cols, referent_table, remote_cols, ondelete in FK_SPECS:
        _create_not_valid_foreign_key(
            name,
            source_table,
            local_cols,
            referent_table,
            remote_cols,
            ondelete=ondelete,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name, source_table, *_ in reversed(FK_SPECS):
            _drop_foreign_key_if_exists(name, source_table)

    for name, table_name, _columns in reversed(INDEX_SPECS):
        _drop_index_if_exists(name, table_name)


def _create_indexes() -> None:
    for name, table_name, columns in INDEX_SPECS:
        _create_index_if_possible(name, table_name, columns)


def _create_index_if_possible(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return
    table_columns = {item["name"] for item in inspector.get_columns(table_name)}
    if not set(columns).issubset(table_columns):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)


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


def _drop_foreign_key_if_exists(name: str, source_table: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if source_table not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_foreign_keys(source_table)}
    if name in existing:
        op.drop_constraint(name, source_table, type_="foreignkey")


def _drop_index_if_exists(name: str, table_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)
