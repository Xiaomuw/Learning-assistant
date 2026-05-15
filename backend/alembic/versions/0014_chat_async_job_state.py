"""extend chat async job state

Revision ID: 0014_chat_async_job_state
Revises: 0013_chat_async_jobs
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0014_chat_async_job_state"
down_revision: str | None = "0013_chat_async_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON_TYPE = sa.JSON()


def upgrade() -> None:
    if "chat_async_jobs" not in _tables():
        return

    _add_column_if_missing("chat_async_jobs", sa.Column("conversation_id", sa.String(100), nullable=False, server_default=""))
    _add_column_if_missing("chat_async_jobs", sa.Column("client_request_id", sa.String(160), nullable=True))
    _add_column_if_missing("chat_async_jobs", sa.Column("trace_id", sa.String(160), nullable=False, server_default=""))
    _add_column_if_missing("chat_async_jobs", sa.Column("request_payload", JSON_TYPE, nullable=True))
    _add_column_if_missing("chat_async_jobs", sa.Column("final_answer", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("chat_async_jobs", sa.Column("error_code", sa.String(80), nullable=False, server_default=""))
    _add_column_if_missing("chat_async_jobs", sa.Column("error_message", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("chat_async_jobs", sa.Column("route", sa.String(50), nullable=False, server_default=""))
    _add_column_if_missing("chat_async_jobs", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))

    _create_index("ix_chat_async_jobs_conversation_id", "chat_async_jobs", ["conversation_id"])
    _create_index("ix_chat_async_jobs_client_request_id", "chat_async_jobs", ["client_request_id"])
    _create_index("ix_chat_async_jobs_trace_id", "chat_async_jobs", ["trace_id"])
    _create_index("ix_chat_async_jobs_expires_at", "chat_async_jobs", ["expires_at"])
    _create_index(
        "idx_chat_async_jobs_user_client_request",
        "chat_async_jobs",
        ["user_id", "client_request_id"],
    )


def downgrade() -> None:
    # Keep downgrade conservative for SQLite compatibility in tests and local dev.
    for name in (
        "idx_chat_async_jobs_user_client_request",
        "ix_chat_async_jobs_expires_at",
        "ix_chat_async_jobs_trace_id",
        "ix_chat_async_jobs_client_request_id",
        "ix_chat_async_jobs_conversation_id",
    ):
        _drop_index_if_exists(name, "chat_async_jobs")

    if "chat_async_jobs" not in _tables():
        return
    existing = _columns("chat_async_jobs")
    for column_name in (
        "expires_at",
        "route",
        "error_message",
        "error_code",
        "final_answer",
        "request_payload",
        "trace_id",
        "client_request_id",
        "conversation_id",
    ):
        if column_name in existing:
            with op.batch_alter_table("chat_async_jobs") as batch_op:
                batch_op.drop_column(column_name)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {item["name"] for item in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name in _columns(table_name):
        return
    op.add_column(table_name, column)


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name in existing:
        return
    op.create_index(name, table_name, columns)


def _drop_index_if_exists(name: str, table_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        return
    op.drop_index(name, table_name=table_name)
