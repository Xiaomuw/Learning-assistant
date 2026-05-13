"""create chat async job table

Revision ID: 0013_chat_async_jobs
Revises: 0012_core_app_tables
Create Date: 2026-05-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013_chat_async_jobs"
down_revision: str | None = "0012_core_app_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON_TYPE = sa.JSON()


def upgrade() -> None:
    if "chat_async_jobs" not in _tables():
        op.create_table(
            "chat_async_jobs",
            sa.Column("job_id", sa.String(100), primary_key=True),
            sa.Column("user_id", sa.String(100), nullable=False),
            sa.Column("session_id", sa.String(100), nullable=False),
            sa.Column("request_id", sa.String(160), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("result_json", JSON_TYPE, nullable=True),
            sa.Column("error_json", JSON_TYPE, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    _create_index("ix_chat_async_jobs_user_id", "chat_async_jobs", ["user_id"])
    _create_index("ix_chat_async_jobs_session_id", "chat_async_jobs", ["session_id"])
    _create_index("ix_chat_async_jobs_request_id", "chat_async_jobs", ["request_id"])
    _create_index("ix_chat_async_jobs_status", "chat_async_jobs", ["status"])
    _create_index("idx_chat_async_jobs_user_created", "chat_async_jobs", ["user_id", "created_at"])


def downgrade() -> None:
    if "chat_async_jobs" in _tables():
        op.drop_table("chat_async_jobs")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name in existing:
        return
    op.create_index(name, table_name, columns)
