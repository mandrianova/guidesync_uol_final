"""add project profile snapshots

Revision ID: 20260625_0006
Revises: 20260625_0005
Create Date: 2026-06-25 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_0006"
down_revision: str | None = "20260625_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "guidesync_project_profiles"
    index_name = "ix_guidesync_project_profiles_project_version"
    if not inspector.has_table(table_name):
        op.create_table(
            table_name,
            sa.Column("id", sa.String(length=128), primary_key=True),
            sa.Column("project_id", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("prompt_version", sa.String(length=128), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("architecture", sa.JSON(), nullable=False),
            sa.Column("workflows", sa.JSON(), nullable=False),
            sa.Column("key_terms", sa.JSON(), nullable=False),
            sa.Column("repository_map", sa.JSON(), nullable=False),
            sa.Column("source_refs", sa.JSON(), nullable=False),
            sa.Column("warnings", sa.JSON(), nullable=False),
            sa.Column("uncertainty_notes", sa.JSON(), nullable=False),
            sa.Column("artifact_uris", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        )
    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in existing_indexes:
        op.create_index(index_name, table_name, ["project_id", "version"])


def downgrade() -> None:
    op.drop_index(
        "ix_guidesync_project_profiles_project_version",
        table_name="guidesync_project_profiles",
    )
    op.drop_table("guidesync_project_profiles")
