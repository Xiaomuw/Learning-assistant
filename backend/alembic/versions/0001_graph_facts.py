"""create graph-era facts tables

Revision ID: 0001_graph_facts
Revises:
Create Date: 2026-05-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_graph_facts"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON_TYPE = sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "graph_runs" not in tables:
        op.create_table(
            "graph_runs",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("graph_type", sa.String(40), nullable=False, server_default=""),
            sa.Column("graph_version", sa.String(40), nullable=False, server_default=""),
            sa.Column("run_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("status", sa.String(30), nullable=False, server_default="running"),
            sa.Column("user_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("session_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("thread_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("subject_id", sa.String(64), nullable=False, server_default="general"),
            sa.Column("notebook_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("source_policy", sa.String(40), nullable=False, server_default=""),
            sa.Column("request_mode", sa.String(20), nullable=False, server_default=""),
            sa.Column("langsmith_run_id", sa.String(160), nullable=False, server_default=""),
            sa.Column("sampled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("metadata_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("inputs_summary", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("outputs_summary", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("error_type", sa.String(120), nullable=False, server_default=""),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    else:
        _add_column_if_missing("graph_runs", "langsmith_run_id", sa.Column("langsmith_run_id", sa.String(160), nullable=False, server_default=""))
        _add_column_if_missing("graph_runs", "sampled", sa.Column("sampled", sa.Boolean(), nullable=False, server_default=sa.true()))

    if "node_runs" not in tables:
        op.create_table(
            "node_runs",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("graph_run_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("node_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("status", sa.String(30), nullable=False, server_default="completed"),
            sa.Column("input_summary", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("output_summary", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("error_type", sa.String(120), nullable=False, server_default=""),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "tool_runs" not in tables:
        op.create_table(
            "tool_runs",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("graph_run_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("tool_id", sa.String(160), nullable=False, server_default=""),
            sa.Column("provider", sa.String(80), nullable=False, server_default=""),
            sa.Column("capability", sa.String(80), nullable=False, server_default=""),
            sa.Column("status", sa.String(30), nullable=False, server_default=""),
            sa.Column("input_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("output_summary", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("evidence_refs", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_type", sa.String(120), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "learning_events" not in tables:
        op.create_table(
            "learning_events",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("user_id", sa.String(100), nullable=False),
            sa.Column("concept_id", sa.String(160), nullable=True),
            sa.Column("graph_run_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("payload", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "attempts" not in tables:
        op.create_table(
            "attempts",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("user_id", sa.String(100), nullable=False),
            sa.Column("subject_id", sa.String(64), nullable=False, server_default="general"),
            sa.Column("concept_id", sa.String(160), nullable=False, server_default=""),
            sa.Column("question_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("graph_run_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("source_event_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("is_correct", sa.Boolean(), nullable=True),
            sa.Column("payload", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "mastery_snapshots" not in tables:
        op.create_table(
            "mastery_snapshots",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("user_id", sa.String(100), nullable=False),
            sa.Column("subject_id", sa.String(64), nullable=False, server_default="general"),
            sa.Column("concept_id", sa.String(160), nullable=False),
            sa.Column("p_mastery", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("status", sa.String(30), nullable=False, server_default="learning"),
            sa.Column("evidence_ids", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("payload", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "subject_id", "concept_id", name="uq_mastery_snapshots_user_subject_concept"),
        )

    if "question_items" not in tables:
        op.create_table(
            "question_items",
            sa.Column("id", sa.String(100), primary_key=True),
            sa.Column("user_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("subject_id", sa.String(64), nullable=False, server_default="general"),
            sa.Column("primary_concept_id", sa.String(160), nullable=False, server_default=""),
            sa.Column("graph_run_id", sa.String(100), nullable=False, server_default=""),
            sa.Column("stem", sa.Text(), nullable=False, server_default=""),
            sa.Column("options_json", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("difficulty", sa.String(30), nullable=False, server_default="基础"),
            sa.Column("source_refs", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("answer_key", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("rubric", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("quality_report", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("generation_source", sa.String(120), nullable=False, server_default=""),
            sa.Column("metadata_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if "concepts" not in tables:
        op.create_table(
            "concepts",
            sa.Column("id", sa.String(160), primary_key=True),
            sa.Column("name", sa.String(240), nullable=False, unique=True),
            sa.Column("subject_id", sa.String(64), nullable=False, server_default="general"),
            sa.Column("aliases", JSON_TYPE, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("source", sa.String(80), nullable=False, server_default="graph"),
            sa.Column("metadata_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    _create_indexes()


def downgrade() -> None:
    for name in [
        "concepts",
        "question_items",
        "mastery_snapshots",
        "attempts",
        "learning_events",
        "tool_runs",
        "node_runs",
        "graph_runs",
    ]:
        op.drop_table(name)


def _add_column_if_missing(table_name: str, column_name: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if column_name not in {item["name"] for item in inspector.get_columns(table_name)}:
        op.add_column(table_name, column)


def _create_indexes() -> None:
    _create_index("ix_graph_runs_graph_type", "graph_runs", ["graph_type"])
    _create_index("ix_graph_runs_status", "graph_runs", ["status"])
    _create_index("ix_graph_runs_user_id", "graph_runs", ["user_id"])
    _create_index("ix_graph_runs_session_id", "graph_runs", ["session_id"])
    _create_index("ix_graph_runs_subject_id", "graph_runs", ["subject_id"])
    _create_index("ix_graph_runs_langsmith_run_id", "graph_runs", ["langsmith_run_id"])
    _create_index("ix_node_runs_graph_run_id", "node_runs", ["graph_run_id"])
    _create_index("ix_node_runs_node_name", "node_runs", ["node_name"])
    _create_index("ix_tool_runs_graph_run_id", "tool_runs", ["graph_run_id"])
    _create_index("ix_tool_runs_tool_id", "tool_runs", ["tool_id"])
    _create_index("ix_tool_runs_provider", "tool_runs", ["provider"])
    _create_index("ix_tool_runs_capability", "tool_runs", ["capability"])
    _create_index("ix_tool_runs_status", "tool_runs", ["status"])
    _create_index("ix_learning_events_user_created", "learning_events", ["user_id", "created_at"])
    _create_index("ix_learning_events_event_type", "learning_events", ["event_type"])
    _create_index("ix_learning_events_concept_id", "learning_events", ["concept_id"])
    _create_index("ix_learning_events_graph_run_id", "learning_events", ["graph_run_id"])
    _create_index("ix_attempts_user_id", "attempts", ["user_id"])
    _create_index("ix_attempts_subject_id", "attempts", ["subject_id"])
    _create_index("ix_attempts_concept_id", "attempts", ["concept_id"])
    _create_index("ix_attempts_question_id", "attempts", ["question_id"])
    _create_index("ix_attempts_graph_run_id", "attempts", ["graph_run_id"])
    _create_index("ix_attempts_source_event_id", "attempts", ["source_event_id"])
    _create_index("idx_mastery_snapshots_user_updated", "mastery_snapshots", ["user_id", "updated_at"])
    _create_index("ix_mastery_snapshots_user_id", "mastery_snapshots", ["user_id"])
    _create_index("ix_mastery_snapshots_subject_id", "mastery_snapshots", ["subject_id"])
    _create_index("ix_mastery_snapshots_concept_id", "mastery_snapshots", ["concept_id"])
    _create_index("idx_question_items_subject_concept", "question_items", ["subject_id", "primary_concept_id"])
    _create_index("ix_question_items_user_id", "question_items", ["user_id"])
    _create_index("ix_question_items_graph_run_id", "question_items", ["graph_run_id"])
    _create_index("ix_concepts_name", "concepts", ["name"])
    _create_index("ix_concepts_subject_id", "concepts", ["subject_id"])


def _create_index(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)
