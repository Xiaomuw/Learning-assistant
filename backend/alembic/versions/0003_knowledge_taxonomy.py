"""create knowledge taxonomy registry tables

Revision ID: 0003_knowledge_taxonomy
Revises: 0002_wechat_mini_identities
Create Date: 2026-05-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_knowledge_taxonomy"
down_revision: str | None = "0002_wechat_mini_identities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON_TYPE = sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "kb_subject" not in tables:
        op.create_table(
            "kb_subject",
            sa.Column("subject_id", sa.String(64), primary_key=True),
            sa.Column("subject_name", sa.String(160), nullable=False, server_default=""),
            sa.Column("metadata_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "kb_chapter" not in tables:
        op.create_table(
            "kb_chapter",
            sa.Column("chapter_id", sa.String(160), primary_key=True),
            sa.Column("subject_id", sa.String(64), nullable=False),
            sa.Column("chapter_name", sa.String(240), nullable=False, server_default=""),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "kb_topic" not in tables:
        op.create_table(
            "kb_topic",
            sa.Column("topic_id", sa.String(180), primary_key=True),
            sa.Column("subject_id", sa.String(64), nullable=False),
            sa.Column("chapter_id", sa.String(160), nullable=False),
            sa.Column("topic_name", sa.String(240), nullable=False, server_default=""),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "kb_concept" not in tables:
        op.create_table(
            "kb_concept",
            sa.Column("concept_id", sa.String(200), primary_key=True),
            sa.Column("subject_id", sa.String(64), nullable=False),
            sa.Column("chapter_id", sa.String(160), nullable=False),
            sa.Column("topic_id", sa.String(180), nullable=False),
            sa.Column("concept_name", sa.String(240), nullable=False, server_default=""),
            sa.Column("aliases_json", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("prerequisites_json", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("importance", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("exam_frequency", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("question_types_json", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("metadata_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "kb_chunk" not in tables:
        op.create_table(
            "kb_chunk",
            sa.Column("id", sa.String(120), primary_key=True),
            sa.Column("vector_id", sa.String(240), nullable=False, server_default=""),
            sa.Column("subject_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("subject_name", sa.String(160), nullable=False, server_default=""),
            sa.Column("chapter_id", sa.String(160), nullable=False, server_default=""),
            sa.Column("chapter_name", sa.String(240), nullable=False, server_default=""),
            sa.Column("topic_id", sa.String(180), nullable=False, server_default=""),
            sa.Column("topic_name", sa.String(240), nullable=False, server_default=""),
            sa.Column("concept_id", sa.String(200), nullable=False, server_default=""),
            sa.Column("concept_name", sa.String(240), nullable=False, server_default=""),
            sa.Column("source_file", sa.String(500), nullable=False, server_default=""),
            sa.Column("page_start", sa.Integer(), nullable=True),
            sa.Column("page_end", sa.Integer(), nullable=True),
            sa.Column("mapping_status", sa.String(30), nullable=False, server_default="unmapped"),
            sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    for table_name in ("question_bank_items", "practice_attempts", "user_knowledge_stats"):
        if table_name in tables:
            _add_concept_columns(table_name)

    _create_indexes()


def downgrade() -> None:
    for table_name in ("question_bank_items", "practice_attempts", "user_knowledge_stats"):
        for column_name in ("concept_mapping_status", "concept_name", "concept_id", "topic_id", "chapter_id"):
            _drop_column_if_exists(table_name, column_name)
    for table_name in ["kb_chunk", "kb_concept", "kb_topic", "kb_chapter", "kb_subject"]:
        op.drop_table(table_name)


def _add_concept_columns(table_name: str) -> None:
    _add_column_if_missing(table_name, "chapter_id", sa.Column("chapter_id", sa.String(160), nullable=True, server_default=""))
    _add_column_if_missing(table_name, "topic_id", sa.Column("topic_id", sa.String(180), nullable=True, server_default=""))
    _add_column_if_missing(table_name, "concept_id", sa.Column("concept_id", sa.String(200), nullable=True, server_default=""))
    _add_column_if_missing(table_name, "concept_name", sa.Column("concept_name", sa.String(240), nullable=True, server_default=""))
    _add_column_if_missing(table_name, "concept_mapping_status", sa.Column("concept_mapping_status", sa.String(30), nullable=True, server_default=""))


def _add_column_if_missing(table_name: str, column_name: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    if column_name not in {item["name"] for item in inspector.get_columns(table_name)}:
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name in set(inspector.get_table_names()) and column_name in {item["name"] for item in inspector.get_columns(table_name)}:
        op.drop_column(table_name, column_name)


def _create_indexes() -> None:
    _create_index("ix_kb_chapter_subject_id", "kb_chapter", ["subject_id"])
    _create_index("ix_kb_topic_subject_id", "kb_topic", ["subject_id"])
    _create_index("ix_kb_topic_chapter_id", "kb_topic", ["chapter_id"])
    _create_index("ix_kb_concept_subject_id", "kb_concept", ["subject_id"])
    _create_index("ix_kb_concept_chapter_id", "kb_concept", ["chapter_id"])
    _create_index("ix_kb_concept_topic_id", "kb_concept", ["topic_id"])
    _create_index("ix_kb_concept_concept_name", "kb_concept", ["concept_name"])
    _create_index("ix_kb_chunk_vector_id", "kb_chunk", ["vector_id"])
    _create_index("ix_kb_chunk_subject_id", "kb_chunk", ["subject_id"])
    _create_index("ix_kb_chunk_chapter_id", "kb_chunk", ["chapter_id"])
    _create_index("ix_kb_chunk_topic_id", "kb_chunk", ["topic_id"])
    _create_index("ix_kb_chunk_concept_id", "kb_chunk", ["concept_id"])
    _create_index("ix_kb_chunk_source_file", "kb_chunk", ["source_file"])
    _create_index("ix_kb_chunk_mapping_status", "kb_chunk", ["mapping_status"])
    _create_index("ix_kb_chunk_content_hash", "kb_chunk", ["content_hash"])
    _create_index("idx_kb_chunk_subject_concept", "kb_chunk", ["subject_id", "concept_id"])
    _create_index("idx_kb_chunk_source_status", "kb_chunk", ["source_file", "mapping_status"])
    for table_name in ("question_bank_items", "practice_attempts", "user_knowledge_stats"):
        _create_index(f"ix_{table_name}_concept_id", table_name, ["concept_id"])


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)
