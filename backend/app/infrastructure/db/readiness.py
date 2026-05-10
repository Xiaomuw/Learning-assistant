from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.infrastructure.db import models as _models  # noqa: F401 - populate Base metadata
from app.infrastructure.db.database import Base, current_database_backend, engine


PGVECTOR_COLLECTION_TABLE = "langchain_pg_collection"
PGVECTOR_EMBEDDING_TABLE = "langchain_pg_embedding"

REQUIRED_PGVECTOR_INDEXES: dict[str, set[str]] = {
    PGVECTOR_COLLECTION_TABLE: {"ix_langchain_pg_collection_name"},
    PGVECTOR_EMBEDDING_TABLE: {
        "ix_langchain_pg_embedding_collection_id",
        "ix_langchain_pg_embedding_custom_id",
        "uq_langchain_pg_embedding_collection_custom_id",
        "ix_langchain_pg_embedding_cmetadata_gin",
        "ix_langchain_pg_embedding_cmetadata_source_id",
        "ix_langchain_pg_embedding_cmetadata_doc_type",
        "ix_langchain_pg_embedding_cmetadata_concept_id",
        "ix_langchain_pg_embedding_cmetadata_topic_id",
    },
}


@dataclass(frozen=True)
class DatabaseReadinessReport:
    database_backend: str
    alembic_heads: tuple[str, ...]
    alembic_current_revisions: tuple[str, ...]
    required_table_count: int
    required_index_count: int
    vector_extension_ready: bool
    missing_tables: tuple[str, ...] = ()
    missing_indexes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def assert_database_readiness() -> DatabaseReadinessReport:
    """Run startup-blocking, read-only database readiness checks."""

    backend = current_database_backend()
    if backend != "postgresql":
        raise RuntimeError(f"数据库 readiness 失败：当前后端不是 PostgreSQL，backend={backend}")

    check_database_connection()
    alembic_heads, current_revisions = check_alembic_head()
    schema_status = inspect_schema_readiness()
    vector_extension_ready = is_vector_extension_installed()

    report = DatabaseReadinessReport(
        database_backend=backend,
        alembic_heads=alembic_heads,
        alembic_current_revisions=current_revisions,
        required_table_count=len(required_table_names()),
        required_index_count=sum(len(indexes) for indexes in required_index_names_by_table().values()),
        vector_extension_ready=vector_extension_ready,
        missing_tables=schema_status["missing_tables"],
        missing_indexes=schema_status["missing_indexes"],
    )

    problems: list[str] = []
    if not vector_extension_ready:
        problems.append("缺少 PostgreSQL vector extension")
    if report.missing_tables:
        problems.append(f"缺少必要表: {', '.join(report.missing_tables)}")
    if report.missing_indexes:
        problems.append(f"缺少必要索引: {', '.join(report.missing_indexes)}")
    if problems:
        raise RuntimeError("数据库 readiness 失败：" + "；".join(problems))

    return report


def check_database_connection() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()


def check_alembic_head() -> tuple[tuple[str, ...], tuple[str, ...]]:
    heads = _load_alembic_heads()
    current_revisions = _load_current_alembic_revisions()
    if set(current_revisions) != set(heads):
        raise RuntimeError(
            "数据库 readiness 失败：Alembic revision 不在 head，"
            f"current={','.join(current_revisions) or '<empty>'}, "
            f"head={','.join(heads) or '<empty>'}"
        )
    return heads, current_revisions


def inspect_schema_readiness() -> dict[str, tuple[str, ...]]:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    missing_tables = tuple(sorted(required_table_names() - table_names))
    missing_table_set = set(missing_tables)
    missing_indexes: list[str] = []

    for table_name, required_indexes in required_index_names_by_table().items():
        if table_name in missing_table_set:
            continue
        actual_indexes = {
            str(index["name"])
            for index in inspector.get_indexes(table_name)
            if index.get("name")
        }
        for index_name in sorted(required_indexes - actual_indexes):
            missing_indexes.append(f"{table_name}.{index_name}")

    return {
        "missing_tables": missing_tables,
        "missing_indexes": tuple(missing_indexes),
    }


def required_table_names() -> set[str]:
    return {
        "alembic_version",
        PGVECTOR_COLLECTION_TABLE,
        PGVECTOR_EMBEDDING_TABLE,
        *Base.metadata.tables.keys(),
    }


def required_index_names_by_table() -> dict[str, set[str]]:
    required: dict[str, set[str]] = {}
    for table_name, table in Base.metadata.tables.items():
        index_names = {str(index.name) for index in table.indexes if index.name}
        if index_names:
            required[table_name] = index_names
    for table_name, index_names in REQUIRED_PGVECTOR_INDEXES.items():
        required.setdefault(table_name, set()).update(index_names)
    return required


def is_vector_extension_installed() -> bool:
    with engine.connect() as connection:
        installed = connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_extension
                    WHERE extname = 'vector'
                )
                """
            )
        ).scalar()
    return bool(installed)


def _load_current_alembic_revisions() -> tuple[str, ...]:
    inspector = inspect(engine)
    if "alembic_version" not in set(inspector.get_table_names()):
        raise RuntimeError("数据库 readiness 失败：未找到 alembic_version，请先运行 Alembic migration")
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    return tuple(sorted(str(row) for row in rows if row))


def _load_alembic_heads() -> tuple[str, ...]:
    script = ScriptDirectory.from_config(_alembic_config())
    return tuple(sorted(script.get_heads()))


def _alembic_config() -> Config:
    backend_root = Path(__file__).resolve().parents[3]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return config
