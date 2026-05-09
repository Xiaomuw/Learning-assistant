"""create wechat mini identities table

Revision ID: 0002_wechat_mini_identities
Revises: 0001_graph_facts
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_wechat_mini_identities"
down_revision: str | None = "0001_graph_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "wechat_mini_identities" not in tables:
        op.create_table(
            "wechat_mini_identities",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("user_id", sa.String(100), nullable=False),
            sa.Column("openid", sa.String(128), nullable=False),
            sa.Column("unionid", sa.String(128), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("openid", name="uq_wechat_mini_identities_openid"),
        )

    _create_index("ix_wechat_mini_identities_user_id", "wechat_mini_identities", ["user_id"])
    _create_index("ix_wechat_mini_identities_openid", "wechat_mini_identities", ["openid"])
    _create_index("ix_wechat_mini_identities_unionid", "wechat_mini_identities", ["unionid"])


def downgrade() -> None:
    op.drop_table("wechat_mini_identities")


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)
