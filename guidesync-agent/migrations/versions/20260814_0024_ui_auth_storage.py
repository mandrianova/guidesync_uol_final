"""support typed write-only UI browser authorization

Revision ID: 20260814_0024
Revises: 20260814_0023
Create Date: 2026-08-14 09:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0024"
down_revision: str | None = "20260814_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "guidesync_projects",
        "task_interface_auth_cookie",
        new_column_name="task_interface_auth_secret",
    )
    op.add_column(
        "guidesync_projects",
        sa.Column("task_interface_auth_type", sa.String(length=32), nullable=True),
    )
    op.execute(
        "UPDATE guidesync_projects SET task_interface_auth_type = 'cookie' "
        "WHERE task_interface_auth_secret IS NOT NULL"
    )
    op.alter_column(
        "guidesync_report_runs",
        "task_interface_auth_cookie",
        new_column_name="task_interface_auth_secret",
    )
    op.add_column(
        "guidesync_report_runs",
        sa.Column("task_interface_auth_type", sa.String(length=32), nullable=True),
    )
    op.execute(
        "UPDATE guidesync_report_runs SET task_interface_auth_type = 'cookie' "
        "WHERE task_interface_auth_secret IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("guidesync_report_runs", "task_interface_auth_type")
    op.alter_column(
        "guidesync_report_runs",
        "task_interface_auth_secret",
        new_column_name="task_interface_auth_cookie",
    )
    op.drop_column("guidesync_projects", "task_interface_auth_type")
    op.alter_column(
        "guidesync_projects",
        "task_interface_auth_secret",
        new_column_name="task_interface_auth_cookie",
    )
