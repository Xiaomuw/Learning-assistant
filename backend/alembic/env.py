from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool


load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_override_database_url = os.getenv("ALEMBIC_DATABASE_URL", "").strip()

if _override_database_url:
    # Test and CI smoke runs can point Alembic at an isolated database without
    # importing the application DB bootstrap, which intentionally rejects
    # non-PostgreSQL DSNs.
    target_metadata = None
else:
    from app.infrastructure.db.database import Base
    from app.infrastructure.db import models  # noqa: F401

    target_metadata = Base.metadata


def _database_url() -> str:
    if _override_database_url:
        return _override_database_url
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    from app.infrastructure.db.database import get_sqlalchemy_database_url

    return get_sqlalchemy_database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
