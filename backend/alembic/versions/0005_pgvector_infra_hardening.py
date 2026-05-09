"""harden pgvector infrastructure indexes

Revision ID: 0005_pgvector_infra_hardening
Revises: 0004_practice_question_import
Create Date: 2026-05-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_pgvector_infra_hardening"
down_revision: str | None = "0004_practice_question_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


COLLECTION_TABLE = "langchain_pg_collection"
EMBEDDING_TABLE = "langchain_pg_embedding"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if COLLECTION_TABLE in tables:
        _create_index(
            "ix_langchain_pg_collection_name",
            f"CREATE INDEX IF NOT EXISTS ix_langchain_pg_collection_name ON {COLLECTION_TABLE} (name)",
        )

    if EMBEDDING_TABLE not in tables:
        return

    if not _has_column(EMBEDDING_TABLE, "custom_id"):
        op.add_column(EMBEDDING_TABLE, sa.Column("custom_id", sa.Text(), nullable=True))

    if _has_column(EMBEDDING_TABLE, "collection_id"):
        _create_index(
            "ix_langchain_pg_embedding_collection_id",
            f"CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_collection_id ON {EMBEDDING_TABLE} (collection_id)",
        )
    _create_index(
        "ix_langchain_pg_embedding_custom_id",
        f"CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_custom_id ON {EMBEDDING_TABLE} (custom_id)",
    )
    _create_custom_id_unique_index()

    if _has_column(EMBEDDING_TABLE, "cmetadata"):
        _create_index(
            "ix_langchain_pg_embedding_cmetadata_gin",
            f"CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_cmetadata_gin ON {EMBEDDING_TABLE} USING gin ((cmetadata::jsonb))",
        )
        for key in ("source_id", "doc_type", "concept_id", "topic_id"):
            _create_index(
                f"ix_langchain_pg_embedding_cmetadata_{key}",
                (
                    f"CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_cmetadata_{key} "
                    f"ON {EMBEDDING_TABLE} (((cmetadata::jsonb ->> '{key}')))"
                ),
            )


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


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return False
    return column_name in {item["name"] for item in inspector.get_columns(table_name)}


def _create_index(index_name: str, sql: str) -> None:
    if not _index_exists(index_name):
        op.execute(sa.text(sql))


def _create_custom_id_unique_index() -> None:
    index_name = "uq_langchain_pg_embedding_collection_custom_id"
    if (
        _index_exists(index_name)
        or not _has_column(EMBEDDING_TABLE, "collection_id")
        or not _has_column(EMBEDDING_TABLE, "custom_id")
    ):
        return

    duplicate_exists = op.get_bind().execute(
        sa.text(
            f"""
            SELECT EXISTS (
                SELECT 1
                FROM (
                    SELECT collection_id, custom_id
                    FROM {EMBEDDING_TABLE}
                    WHERE custom_id IS NOT NULL AND custom_id <> ''
                    GROUP BY collection_id, custom_id
                    HAVING COUNT(*) > 1
                ) duplicate_custom_ids
            )
            """
        )
    ).scalar()
    if duplicate_exists:
        return

    op.execute(
        sa.text(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
            ON {EMBEDDING_TABLE} (collection_id, custom_id)
            WHERE custom_id IS NOT NULL AND custom_id <> ''
            """
        )
    )


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
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
