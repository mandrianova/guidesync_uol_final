"""add project profile agent metadata

Revision ID: 20260627_0008
Revises: 20260626_0007
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0008"
down_revision: str | None = "20260626_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("guidesync_project_profiles"):
        return
    columns = {column["name"] for column in inspector.get_columns("guidesync_project_profiles")}
    with op.batch_alter_table("guidesync_project_profiles") as batch_op:
        if "model_metadata" not in columns:
            batch_op.add_column(sa.Column("model_metadata", sa.JSON(), nullable=True))
        if "tool_trace_refs" not in columns:
            batch_op.add_column(sa.Column("tool_trace_refs", sa.JSON(), nullable=True))
        if "validation_findings" not in columns:
            batch_op.add_column(sa.Column("validation_findings", sa.JSON(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE guidesync_project_profiles "
            "SET model_metadata = '{}' WHERE model_metadata IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE guidesync_project_profiles "
            "SET tool_trace_refs = '[]' WHERE tool_trace_refs IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE guidesync_project_profiles "
            "SET validation_findings = '[]' WHERE validation_findings IS NULL"
        )
    )
    with op.batch_alter_table("guidesync_project_profiles") as batch_op:
        batch_op.alter_column("model_metadata", nullable=False)
        batch_op.alter_column("tool_trace_refs", nullable=False)
        batch_op.alter_column("validation_findings", nullable=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_project_profiles"):
        return
    columns = {column["name"] for column in inspector.get_columns("guidesync_project_profiles")}
    with op.batch_alter_table("guidesync_project_profiles") as batch_op:
        if "validation_findings" in columns:
            batch_op.drop_column("validation_findings")
        if "tool_trace_refs" in columns:
            batch_op.drop_column("tool_trace_refs")
        if "model_metadata" in columns:
            batch_op.drop_column("model_metadata")
