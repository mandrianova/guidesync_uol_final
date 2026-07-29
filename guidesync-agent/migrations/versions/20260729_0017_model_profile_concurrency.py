"""persist model profile agent concurrency

Revision ID: 20260729_0017
Revises: 20260728_0016
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0017"
down_revision: str | None = "20260728_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guidesync_model_profiles",
        sa.Column(
            "max_concurrent_agents",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_guidesync_model_profiles_max_concurrent_agents_positive",
        "guidesync_model_profiles",
        "max_concurrent_agents >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_guidesync_model_profiles_max_concurrent_agents_positive",
        "guidesync_model_profiles",
        type_="check",
    )
    op.drop_column("guidesync_model_profiles", "max_concurrent_agents")
