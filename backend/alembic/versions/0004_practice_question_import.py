"""create standalone practice question import table

Revision ID: 0004_practice_question_import
Revises: 0003_knowledge_taxonomy
Create Date: 2026-05-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_practice_question_import"
down_revision: str | None = "0003_knowledge_taxonomy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON_TYPE = sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "practice_question" not in tables:
        op.create_table(
            "practice_question",
            sa.Column("question_id", sa.String(120), primary_key=True),
            sa.Column("subject_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("subject_name", sa.String(160), nullable=False, server_default=""),
            sa.Column("chapter_name", sa.String(240), nullable=False, server_default=""),
            sa.Column("topic_name", sa.String(240), nullable=False, server_default=""),
            sa.Column("concept_id", sa.String(200), nullable=False, server_default=""),
            sa.Column("concept_name", sa.String(240), nullable=False, server_default=""),
            sa.Column("difficulty", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("stem", sa.Text(), nullable=False, server_default=""),
            sa.Column("options_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("answer", sa.String(1), nullable=False, server_default="A"),
            sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
            sa.Column("knowledge_points_json", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("common_trap", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("source_file", sa.String(500), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    _create_index("ix_practice_question_concept_id", "practice_question", ["concept_id"])
    _create_index("ix_practice_question_subject_id", "practice_question", ["subject_id"])
    _create_index("ix_practice_question_difficulty", "practice_question", ["difficulty"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "practice_question" in set(inspector.get_table_names()):
        op.drop_table("practice_question")


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)
