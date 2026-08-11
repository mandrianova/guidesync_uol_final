"""store publication reports with their runs

Revision ID: 20260811_0020
Revises: 20260808_0019
Create Date: 2026-08-11 22:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0020"
down_revision: str | None = "20260808_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guidesync_report_runs",
        sa.Column("publication_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guidesync_report_runs", "publication_snapshot")
