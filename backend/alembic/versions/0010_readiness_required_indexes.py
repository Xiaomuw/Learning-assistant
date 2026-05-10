"""add indexes required by startup readiness

Revision ID: 0010_readiness_required_indexes
Revises: 0009_pgvector_core_tables
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_readiness_required_indexes"
down_revision: str | None = "0009_pgvector_core_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_SPECS: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_learning_events_user_id", "learning_events", ["user_id"]),
    ("idx_learning_events_user_created", "learning_events", ["user_id", "created_at"]),
    ("ix_question_items_subject_id", "question_items", ["subject_id"]),
    ("ix_question_items_primary_concept_id", "question_items", ["primary_concept_id"]),
)


def upgrade() -> None:
    for name, table_name, columns in INDEX_SPECS:
        _create_index_if_possible(name, table_name, columns)


def downgrade() -> None:
    for name, table_name, _columns in reversed(INDEX_SPECS):
        _drop_index_if_exists(name, table_name)


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


def _drop_index_if_exists(name: str, table_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)
