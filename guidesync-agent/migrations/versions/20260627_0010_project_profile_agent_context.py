"""add project profile agent context fields

Revision ID: 20260627_0010
Revises: 20260627_0009
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0010"
down_revision: str | None = "20260627_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_project_profiles"):
        return
    columns = {column["name"] for column in inspector.get_columns("guidesync_project_profiles")}
    with op.batch_alter_table("guidesync_project_profiles") as batch_op:
        if "project_description" not in columns:
            batch_op.add_column(sa.Column("project_description", sa.Text(), nullable=True))
        if "project_structure" not in columns:
            batch_op.add_column(sa.Column("project_structure", sa.JSON(), nullable=True))
        if "core_concepts" not in columns:
            batch_op.add_column(sa.Column("core_concepts", sa.JSON(), nullable=True))
        if "agent_context" not in columns:
            batch_op.add_column(sa.Column("agent_context", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE guidesync_project_profiles "
            "SET project_description = '' WHERE project_description IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE guidesync_project_profiles "
            "SET project_structure = '[]' WHERE project_structure IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE guidesync_project_profiles "
            "SET core_concepts = '[]' WHERE core_concepts IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE guidesync_project_profiles "
            "SET agent_context = '' WHERE agent_context IS NULL"
        )
    )
    with op.batch_alter_table("guidesync_project_profiles") as batch_op:
        batch_op.alter_column("project_description", nullable=False)
        batch_op.alter_column("project_structure", nullable=False)
        batch_op.alter_column("core_concepts", nullable=False)
        batch_op.alter_column("agent_context", nullable=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_project_profiles"):
        return
    columns = {column["name"] for column in inspector.get_columns("guidesync_project_profiles")}
    with op.batch_alter_table("guidesync_project_profiles") as batch_op:
        if "agent_context" in columns:
            batch_op.drop_column("agent_context")
        if "core_concepts" in columns:
            batch_op.drop_column("core_concepts")
        if "project_structure" in columns:
            batch_op.drop_column("project_structure")
        if "project_description" in columns:
            batch_op.drop_column("project_description")
