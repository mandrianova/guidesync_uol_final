"""store write-only UI authentication cookies

Revision ID: 20260814_0023
Revises: 20260813_0022
Create Date: 2026-08-14 01:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0023"
down_revision: str | None = "20260813_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guidesync_projects",
        sa.Column("task_interface_auth_cookie", sa.Text(), nullable=True),
    )
    op.add_column(
        "guidesync_report_runs",
        sa.Column("task_interface_auth_cookie", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guidesync_report_runs", "task_interface_auth_cookie")
    op.drop_column("guidesync_projects", "task_interface_auth_cookie")
