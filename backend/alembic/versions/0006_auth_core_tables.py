"""create auth core tables

Revision ID: 0006_auth_core_tables
Revises: 0005_pgvector_infra_hardening
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_auth_core_tables"
down_revision: str | None = "0005_pgvector_infra_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON_TYPE = sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )
    _create_index("ix_users_email", "users", ["email"])

    if "user_profiles" not in tables:
        op.create_table(
            "user_profiles",
            sa.Column("user_id", sa.String(100), primary_key=True),
            sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("agent_style_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("agent_style_prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "user_memories" not in tables:
        op.create_table(
            "user_memories",
            sa.Column("user_id", sa.String(100), primary_key=True),
            sa.Column("weak_points", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("error_count", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("recent_topics", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("last_session", sa.String(200), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "auth_refresh_tokens" not in tables:
        op.create_table(
            "auth_refresh_tokens",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("user_id", sa.String(100), nullable=False),
            sa.Column("token_jti", sa.String(100), nullable=False),
            sa.Column("token_hash", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_jti", name="uq_auth_refresh_tokens_token_jti"),
        )
    _create_index("ix_auth_refresh_tokens_user_id", "auth_refresh_tokens", ["user_id"])
    _create_index("ix_auth_refresh_tokens_token_jti", "auth_refresh_tokens", ["token_jti"])

    if "email_verification_challenges" not in tables:
        op.create_table(
            "email_verification_challenges",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("purpose", sa.String(50), nullable=False, server_default="register"),
            sa.Column("code_hash", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    _create_index("ix_email_verification_challenges_email", "email_verification_challenges", ["email"])
    _create_index("ix_email_verification_challenges_purpose", "email_verification_challenges", ["purpose"])
    _create_index(
        "idx_email_verification_challenges_email_purpose_active",
        "email_verification_challenges",
        ["email", "purpose", "consumed_at", "verified_at"],
    )


def downgrade() -> None:
    for table_name in (
        "email_verification_challenges",
        "auth_refresh_tokens",
        "user_memories",
        "user_profiles",
        "users",
    ):
        op.drop_table(table_name)


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)
