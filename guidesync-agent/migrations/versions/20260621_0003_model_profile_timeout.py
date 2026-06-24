"""persist model profile timeout

Revision ID: 20260621_0003
Revises: 20260619_0002
Create Date: 2026-06-21 18:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260621_0003"
down_revision: str | None = "20260619_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guidesync_model_profiles",
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"),
    )


def downgrade() -> None:
    op.drop_column("guidesync_model_profiles", "timeout_seconds")
