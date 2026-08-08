"""add workflow task attempts and leases

Revision ID: 20260808_0018
Revises: 20260729_0017
Create Date: 2026-08-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0018"
down_revision: str | None = "20260729_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guidesync_project_workflow_tasks",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "guidesync_project_workflow_tasks",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "guidesync_project_workflow_tasks",
        sa.Column("lease_token", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "guidesync_project_workflow_tasks",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "guidesync_project_workflow_tasks",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guidesync_project_workflow_tasks", "last_heartbeat_at")
    op.drop_column("guidesync_project_workflow_tasks", "lease_expires_at")
    op.drop_column("guidesync_project_workflow_tasks", "lease_token")
    op.drop_column("guidesync_project_workflow_tasks", "max_attempts")
    op.drop_column("guidesync_project_workflow_tasks", "attempt_count")
