"""store the default project UI URL

Revision ID: 20260813_0022
Revises: 20260812_0021
Create Date: 2026-08-13 23:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0022"
down_revision: str | None = "20260812_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guidesync_projects",
        sa.Column("task_interface_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guidesync_projects", "task_interface_url")
