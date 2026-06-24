"""persist model profile thinking setting

Revision ID: 20260624_0004
Revises: 20260621_0003
Create Date: 2026-06-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260624_0004"
down_revision: str | None = "20260621_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guidesync_model_profiles",
        sa.Column("thinking", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guidesync_model_profiles", "thinking")
