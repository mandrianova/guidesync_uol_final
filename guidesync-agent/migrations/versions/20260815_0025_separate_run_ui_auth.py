"""separate report-run UI authorization secrets

Revision ID: 20260815_0025
Revises: 20260814_0024
Create Date: 2026-08-15 07:25:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_0025"
down_revision: str | None = "20260814_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guidesync_run_ui_auth_secrets",
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("auth_secret", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["guidesync_report_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.drop_column("guidesync_report_runs", "task_interface_auth_secret")


def downgrade() -> None:
    op.add_column(
        "guidesync_report_runs",
        sa.Column("task_interface_auth_secret", sa.Text(), nullable=True),
    )
    op.drop_table("guidesync_run_ui_auth_secrets")
