"""remove report-run model override columns

Revision ID: 20260628_0015
Revises: 20260628_0014
Create Date: 2026-06-28 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260628_0015"
down_revision: str | None = "20260628_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_report_runs"):
        return
    columns = {column["name"] for column in inspector.get_columns("guidesync_report_runs")}
    with op.batch_alter_table("guidesync_report_runs") as batch_op:
        if "model_profile_id" in columns:
            batch_op.drop_column("model_profile_id")
        if "requested_model_settings" in columns:
            batch_op.drop_column("requested_model_settings")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_report_runs"):
        return
    columns = {column["name"] for column in inspector.get_columns("guidesync_report_runs")}
    with op.batch_alter_table("guidesync_report_runs") as batch_op:
        if "model_profile_id" not in columns:
            batch_op.add_column(sa.Column("model_profile_id", sa.String(length=128), nullable=True))
        if "requested_model_settings" not in columns:
            batch_op.add_column(sa.Column("requested_model_settings", sa.JSON(), nullable=True))
