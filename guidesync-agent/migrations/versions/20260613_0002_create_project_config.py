"""create project config tables

Revision ID: 20260613_0002
Revises: 20260613_0001
Create Date: 2026-06-13 00:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260613_0002"
down_revision: str | None = "20260613_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("guidesync_projects"):
        op.create_table(
            "guidesync_projects",
            sa.Column("id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if not inspector.has_table("guidesync_project_repositories"):
        op.create_table(
            "guidesync_project_repositories",
            sa.Column("id", sa.String(length=128), nullable=False),
            sa.Column("project_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("default_branch", sa.String(length=255), nullable=True),
            sa.Column("paths", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not inspector.has_table("guidesync_project_documentation"):
        op.create_table(
            "guidesync_project_documentation",
            sa.Column("id", sa.String(length=128), nullable=False),
            sa.Column("project_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("guidesync_project_documentation"):
        op.drop_table("guidesync_project_documentation")
    if inspector.has_table("guidesync_project_repositories"):
        op.drop_table("guidesync_project_repositories")
    if inspector.has_table("guidesync_projects"):
        op.drop_table("guidesync_projects")
