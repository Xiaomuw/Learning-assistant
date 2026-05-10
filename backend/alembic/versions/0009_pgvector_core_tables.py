"""create pgvector core tables for read-only startup

Revision ID: 0009_pgvector_core_tables
Revises: 0008_core_data_integrity
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_pgvector_core_tables"
down_revision: str | None = "0008_core_data_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    _ensure_collection_table()
    _ensure_embedding_table()
    _ensure_embedding_indexes()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for index_name in (
        "ix_langchain_pg_embedding_cmetadata_topic_id",
        "ix_langchain_pg_embedding_cmetadata_concept_id",
        "ix_langchain_pg_embedding_cmetadata_doc_type",
        "ix_langchain_pg_embedding_cmetadata_source_id",
        "ix_langchain_pg_embedding_cmetadata_gin",
        "uq_langchain_pg_embedding_collection_custom_id",
        "ix_langchain_pg_embedding_custom_id",
        "ix_langchain_pg_embedding_collection_id",
        "ix_langchain_pg_collection_name",
    ):
        op.execute(sa.text(f"DROP INDEX IF EXISTS {index_name}"))
    op.execute(sa.text("DROP TABLE IF EXISTS langchain_pg_embedding"))
    op.execute(sa.text("DROP TABLE IF EXISTS langchain_pg_collection"))


def _ensure_collection_table() -> None:
    inspector = sa.inspect(op.get_bind())
    if "langchain_pg_collection" not in set(inspector.get_table_names()):
        op.execute(
            sa.text(
                """
                CREATE TABLE langchain_pg_collection (
                    uuid UUID PRIMARY KEY,
                    name VARCHAR NOT NULL UNIQUE,
                    cmetadata JSON
                )
                """
            )
        )
    _add_column_if_missing("langchain_pg_collection", "cmetadata", "cmetadata JSON")

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_langchain_pg_collection_name "
            "ON langchain_pg_collection (name)"
        )
    )


def _ensure_embedding_table() -> None:
    inspector = sa.inspect(op.get_bind())
    if "langchain_pg_embedding" not in set(inspector.get_table_names()):
        op.execute(
            sa.text(
                """
                CREATE TABLE langchain_pg_embedding (
                    id VARCHAR PRIMARY KEY,
                    collection_id UUID REFERENCES langchain_pg_collection(uuid) ON DELETE CASCADE,
                    embedding vector,
                    document VARCHAR,
                    cmetadata JSONB,
                    custom_id TEXT
                )
                """
            )
        )
        return

    _add_column_if_missing("langchain_pg_embedding", "custom_id", "custom_id TEXT")
    _add_column_if_missing("langchain_pg_embedding", "cmetadata", "cmetadata JSONB")
    _add_column_if_missing("langchain_pg_embedding", "embedding", "embedding vector")


def _ensure_embedding_indexes() -> None:
    index_statements = (
        """
        CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_collection_id
        ON langchain_pg_embedding (collection_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_custom_id
        ON langchain_pg_embedding (custom_id)
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_langchain_pg_embedding_collection_custom_id
        ON langchain_pg_embedding (collection_id, custom_id)
        WHERE custom_id IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_cmetadata_gin
        ON langchain_pg_embedding USING gin ((cmetadata::jsonb))
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_cmetadata_source_id
        ON langchain_pg_embedding (((cmetadata::jsonb ->> 'source_id')))
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_cmetadata_doc_type
        ON langchain_pg_embedding (((cmetadata::jsonb ->> 'doc_type')))
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_cmetadata_concept_id
        ON langchain_pg_embedding (((cmetadata::jsonb ->> 'concept_id')))
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_cmetadata_topic_id
        ON langchain_pg_embedding (((cmetadata::jsonb ->> 'topic_id')))
        """,
    )
    for statement in index_statements:
        op.execute(sa.text(statement))


def _add_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column_name not in columns:
        op.execute(sa.text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))
