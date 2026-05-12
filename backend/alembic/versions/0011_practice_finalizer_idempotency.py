"""add durable practice finalizer and mastery idempotency fields

Revision ID: 0011_practice_finalizer
Revises: 0010_readiness_required_indexes
Create Date: 2026-05-12
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011_practice_finalizer"
down_revision: str | None = "0010_readiness_required_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_column_if_missing(
        "practice_attempts",
        sa.Column("idempotency_key", sa.String(length=160), nullable=False, server_default=""),
    )
    _add_column_if_missing(
        "user_memories",
        sa.Column("finalized_practice_attempt_ids", _json_type(), nullable=False, server_default=sa.text("'[]'")),
    )
    _add_column_if_missing(
        "mastery_snapshots",
        sa.Column("consumed_signal_ids", _json_type(), nullable=False, server_default=sa.text("'[]'")),
    )
    _add_column_if_missing(
        "mastery_snapshots",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )

    if "practice_attempt_finalization_jobs" not in _tables():
        op.create_table(
            "practice_attempt_finalization_jobs",
            sa.Column("id", sa.String(length=100), nullable=False),
            sa.Column("legacy_attempt_id", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("legacy_attempt_id", name="uq_practice_attempt_finalization_jobs_legacy_attempt_id"),
        )

    _create_index_if_possible(
        "uq_practice_attempts_idempotency_key",
        "practice_attempts",
        ["idempotency_key"],
        unique=True,
        where="idempotency_key IS NOT NULL AND idempotency_key <> ''",
    )
    _create_index_if_possible(
        "ix_practice_attempt_finalization_jobs_legacy_attempt_id",
        "practice_attempt_finalization_jobs",
        ["legacy_attempt_id"],
    )
    _create_index_if_possible(
        "ix_practice_attempt_finalization_jobs_status",
        "practice_attempt_finalization_jobs",
        ["status"],
    )
    _create_index_if_possible(
        "idx_practice_attempt_finalization_jobs_due",
        "practice_attempt_finalization_jobs",
        ["status", "next_run_at"],
    )


def downgrade() -> None:
    for name, table_name in (
        ("idx_practice_attempt_finalization_jobs_due", "practice_attempt_finalization_jobs"),
        ("ix_practice_attempt_finalization_jobs_status", "practice_attempt_finalization_jobs"),
        ("ix_practice_attempt_finalization_jobs_legacy_attempt_id", "practice_attempt_finalization_jobs"),
        ("uq_practice_attempts_idempotency_key", "practice_attempts"),
    ):
        _drop_index_if_exists(name, table_name)
    if "practice_attempt_finalization_jobs" in _tables():
        op.drop_table("practice_attempt_finalization_jobs")
    _drop_column_if_exists("mastery_snapshots", "version")
    _drop_column_if_exists("mastery_snapshots", "consumed_signal_ids")
    _drop_column_if_exists("user_memories", "finalized_practice_attempt_ids")
    _drop_column_if_exists("practice_attempts", "idempotency_key")


def _json_type() -> sa.types.TypeEngine:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB()
    return sa.JSON()


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {item["name"] for item in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if table_name not in _tables() or column.name in _columns(table_name):
        return
    op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if table_name in _tables() and column_name in _columns(table_name):
        op.drop_column(table_name, column_name)


def _create_index_if_possible(
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


def _drop_index_if_exists(name: str, table_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)
