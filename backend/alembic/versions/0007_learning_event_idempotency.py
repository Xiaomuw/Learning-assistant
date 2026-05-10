"""add learning event idempotency hash

Revision ID: 0007_learning_event_idempotency
Revises: 0006_auth_core_tables
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_learning_event_idempotency"
down_revision: str | None = "0006_auth_core_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "learning_events"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return

    if "hash_key" not in {item["name"] for item in inspector.get_columns(TABLE_NAME)}:
        op.add_column(TABLE_NAME, sa.Column("hash_key", sa.String(length=128), nullable=True))

    _create_index(
        "ix_learning_events_hash_key",
        f"CREATE INDEX IF NOT EXISTS ix_learning_events_hash_key ON {TABLE_NAME} (hash_key)",
    )
    _create_index(
        "uq_learning_events_hash_key",
        (
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_events_hash_key "
            f"ON {TABLE_NAME} (hash_key) "
            "WHERE hash_key IS NOT NULL AND hash_key <> ''"
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return

    op.execute(sa.text("DROP INDEX IF EXISTS uq_learning_events_hash_key"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_learning_events_hash_key"))
    if "hash_key" in {item["name"] for item in inspector.get_columns(TABLE_NAME)}:
        op.drop_column(TABLE_NAME, "hash_key")


def _create_index(index_name: str, sql: str) -> None:
    if not _index_exists(index_name):
        op.execute(sa.text(sql))


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        result = bind.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :index_name LIMIT 1"),
            {"index_name": index_name},
        )
        return result.first() is not None
    result = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = ANY (current_schemas(false))
              AND indexname = :index_name
            LIMIT 1
            """
        ),
        {"index_name": index_name},
    )
    return result.first() is not None
