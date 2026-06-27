"""add model call token ledger

Revision ID: 20260627_0012
Revises: 20260627_0011
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0012"
down_revision: str | None = "20260627_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("guidesync_model_call_ledger"):
        return
    op.create_table(
        "guidesync_model_call_ledger",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column("workflow_task_id", sa.String(length=128), nullable=True),
        sa.Column("parent_call_id", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("model_profile_id", sa.String(length=128), nullable=True),
        sa.Column("endpoint_type", sa.String(length=64), nullable=True),
        sa.Column("base_url_host_hash", sa.String(length=64), nullable=True),
        sa.Column("deployment_id", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=128), nullable=True),
        sa.Column("structured_output_schema", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("usage_source", sa.String(length=32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("image_input_tokens", sa.Integer(), nullable=True),
        sa.Column("image_input_units", sa.Integer(), nullable=True),
        sa.Column("embedding_input_tokens", sa.Integer(), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("model_turn_count", sa.Integer(), nullable=False),
        sa.Column("context_compaction_input_tokens", sa.Integer(), nullable=True),
        sa.Column("context_compaction_output_tokens", sa.Integer(), nullable=True),
        sa.Column("provider_reported_total_tokens", sa.Integer(), nullable=True),
        sa.Column("locally_estimated_total_tokens", sa.Integer(), nullable=True),
        sa.Column("request_artifact_ref", sa.Text(), nullable=True),
        sa.Column("response_artifact_ref", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["guidesync_report_runs.id"]),
    )
    op.create_index(
        "ix_guidesync_model_call_ledger_run",
        "guidesync_model_call_ledger",
        ["run_id"],
    )
    op.create_index(
        "ix_guidesync_model_call_ledger_workflow_task",
        "guidesync_model_call_ledger",
        ["workflow_task_id"],
    )
    op.create_index(
        "ix_guidesync_model_call_ledger_role",
        "guidesync_model_call_ledger",
        ["role"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_model_call_ledger"):
        return
    op.drop_index("ix_guidesync_model_call_ledger_role", table_name="guidesync_model_call_ledger")
    op.drop_index(
        "ix_guidesync_model_call_ledger_workflow_task",
        table_name="guidesync_model_call_ledger",
    )
    op.drop_index("ix_guidesync_model_call_ledger_run", table_name="guidesync_model_call_ledger")
    op.drop_table("guidesync_model_call_ledger")
