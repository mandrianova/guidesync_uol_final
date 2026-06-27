"""add llm conversation transcripts

Revision ID: 20260627_0013
Revises: 20260627_0012
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0013"
down_revision: str | None = "20260627_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("guidesync_llm_conversations"):
        return
    op.create_table(
        "guidesync_llm_conversations",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column("workflow_task_id", sa.String(length=128), nullable=True),
        sa.Column("parent_conversation_id", sa.String(length=128), nullable=True),
        sa.Column("model_call_id", sa.String(length=128), nullable=True),
        sa.Column("model_role", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("endpoint_type", sa.String(length=64), nullable=True),
        sa.Column("conversation_id", sa.String(length=255), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("token_ledger_entry_id", sa.String(length=128), nullable=True),
        sa.Column("transcript_artifact_ref", sa.Text(), nullable=True),
        sa.Column("full_history_artifact_ref", sa.Text(), nullable=True),
        sa.Column("redaction_status", sa.String(length=32), nullable=False),
        sa.Column("prompt_metadata", sa.JSON(), nullable=False),
        sa.Column("provider_metadata", sa.JSON(), nullable=False),
        sa.Column("endpoint_metadata", sa.JSON(), nullable=False),
        sa.Column("model_settings", sa.JSON(), nullable=False),
        sa.Column("message_stats", sa.JSON(), nullable=False),
        sa.Column("tool_summary", sa.JSON(), nullable=False),
        sa.Column("redaction_metadata", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["guidesync_report_runs.id"]),
    )
    op.create_index(
        "ix_guidesync_llm_conversations_run",
        "guidesync_llm_conversations",
        ["run_id"],
    )
    op.create_index(
        "ix_guidesync_llm_conversations_workflow_task",
        "guidesync_llm_conversations",
        ["workflow_task_id"],
    )
    op.create_index(
        "ix_guidesync_llm_conversations_model_call",
        "guidesync_llm_conversations",
        ["model_call_id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_llm_conversations"):
        return
    op.drop_index(
        "ix_guidesync_llm_conversations_model_call",
        table_name="guidesync_llm_conversations",
    )
    op.drop_index(
        "ix_guidesync_llm_conversations_workflow_task",
        table_name="guidesync_llm_conversations",
    )
    op.drop_index("ix_guidesync_llm_conversations_run", table_name="guidesync_llm_conversations")
    op.drop_table("guidesync_llm_conversations")
