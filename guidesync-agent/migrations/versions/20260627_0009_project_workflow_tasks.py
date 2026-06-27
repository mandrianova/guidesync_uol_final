"""add project workflow task queue

Revision ID: 20260627_0009
Revises: 20260627_0008
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0009"
down_revision: str | None = "20260627_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_project_workflow_tasks"):
        op.create_table(
            "guidesync_project_workflow_tasks",
            sa.Column("id", sa.String(length=128), primary_key=True),
            sa.Column("project_id", sa.String(length=128), nullable=False),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("depends_on_task_ids", sa.JSON(), nullable=False),
            sa.Column("dedupe_key", sa.Text(), nullable=True),
            sa.Column("requested_by", sa.String(length=32), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("input", sa.JSON(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("warnings", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        )
    create_index_if_missing(
        "ix_guidesync_project_workflow_tasks_project_sequence",
        "guidesync_project_workflow_tasks",
        ["project_id", "sequence"],
    )
    create_index_if_missing(
        "ix_guidesync_project_workflow_tasks_project_status",
        "guidesync_project_workflow_tasks",
        ["project_id", "status"],
    )
    create_index_if_missing(
        "ix_guidesync_project_workflow_tasks_dedupe",
        "guidesync_project_workflow_tasks",
        ["project_id", "dedupe_key"],
    )


def downgrade() -> None:
    drop_index_if_exists(
        "ix_guidesync_project_workflow_tasks_dedupe",
        "guidesync_project_workflow_tasks",
    )
    drop_index_if_exists(
        "ix_guidesync_project_workflow_tasks_project_status",
        "guidesync_project_workflow_tasks",
    )
    drop_index_if_exists(
        "ix_guidesync_project_workflow_tasks_project_sequence",
        "guidesync_project_workflow_tasks",
    )
    op.drop_table("guidesync_project_workflow_tasks")


def create_index_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)


def drop_index_if_exists(name: str, table_name: str) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)
