"""add workflow task progress

Revision ID: 20260808_0019
Revises: 20260808_0018
Create Date: 2026-08-08 00:00:01.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0019"
down_revision: str | None = "20260808_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guidesync_project_workflow_tasks",
        sa.Column(
            "progress",
            sa.JSON(),
            nullable=False,
            server_default=sa.text('\'{"stage": "queued", "message": "Queued"}\''),
        ),
    )


def downgrade() -> None:
    op.drop_column("guidesync_project_workflow_tasks", "progress")
