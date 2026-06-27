"""persist model profile role assignments

Revision ID: 20260627_0011
Revises: 20260627_0010
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0011"
down_revision: str | None = "20260627_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_model_profiles"):
        return
    columns = {column["name"] for column in inspector.get_columns("guidesync_model_profiles")}
    if "roles" not in columns:
        with op.batch_alter_table("guidesync_model_profiles") as batch_op:
            batch_op.add_column(sa.Column("roles", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE guidesync_model_profiles SET roles = '[]' WHERE roles IS NULL"))
    with op.batch_alter_table("guidesync_model_profiles") as batch_op:
        batch_op.alter_column("roles", nullable=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_model_profiles"):
        return
    columns = {column["name"] for column in inspector.get_columns("guidesync_model_profiles")}
    if "roles" in columns:
        with op.batch_alter_table("guidesync_model_profiles") as batch_op:
            batch_op.drop_column("roles")
