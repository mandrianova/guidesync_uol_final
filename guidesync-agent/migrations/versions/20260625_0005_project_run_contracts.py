"""add project and run contract fields

Revision ID: 20260625_0005
Revises: 20260624_0004
Create Date: 2026-06-25 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_0005"
down_revision: str | None = "20260624_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guidesync_projects",
        sa.Column("audience", sa.String(length=64), nullable=False, server_default="end_users"),
    )
    op.add_column(
        "guidesync_projects",
        sa.Column("documentation_instructions", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "guidesync_projects",
        sa.Column("knowledge_base_repository_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "guidesync_projects",
        sa.Column("knowledge_base_ref", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "guidesync_projects",
        sa.Column("knowledge_base_path", sa.Text(), nullable=False, server_default="docs/"),
    )
    op.add_column(
        "guidesync_projects",
        sa.Column("analysis_paths", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("guidesync_projects", sa.Column("credential_ref", sa.Text(), nullable=True))

    op.add_column(
        "guidesync_project_repositories",
        sa.Column("analysis_paths", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.execute(
        "UPDATE guidesync_project_repositories SET analysis_paths = paths "
        "WHERE paths IS NOT NULL"
    )
    op.add_column(
        "guidesync_project_repositories",
        sa.Column("credential_ref", sa.Text(), nullable=True),
    )
    op.add_column(
        "guidesync_project_repositories",
        sa.Column(
            "cache_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_synced",
        ),
    )
    op.add_column(
        "guidesync_project_repositories",
        sa.Column("local_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "guidesync_project_repositories",
        sa.Column("current_commit", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "guidesync_project_repositories",
        sa.Column("cache_warnings", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.drop_column("guidesync_project_repositories", "paths")

    op.add_column(
        "guidesync_project_documentation",
        sa.Column("path", sa.Text(), nullable=True),
    )
    op.drop_column("guidesync_project_documentation", "content")

    op.add_column(
        "guidesync_report_runs",
        sa.Column("task_interface_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "guidesync_report_runs",
        sa.Column(
            "screenshot_policy",
            sa.String(length=32),
            nullable=False,
            server_default="disabled",
        ),
    )
    op.add_column(
        "guidesync_report_runs",
        sa.Column("requested_model_settings", sa.JSON(), nullable=True),
    )
    op.add_column(
        "guidesync_report_runs",
        sa.Column("effective_model_configuration", sa.JSON(), nullable=True),
    )
    op.add_column(
        "guidesync_report_runs",
        sa.Column("project_profile_snapshot_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guidesync_report_runs", "project_profile_snapshot_id")
    op.drop_column("guidesync_report_runs", "effective_model_configuration")
    op.drop_column("guidesync_report_runs", "requested_model_settings")
    op.drop_column("guidesync_report_runs", "screenshot_policy")
    op.drop_column("guidesync_report_runs", "task_interface_url")

    op.add_column(
        "guidesync_project_documentation",
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
    )
    op.drop_column("guidesync_project_documentation", "path")

    op.add_column(
        "guidesync_project_repositories",
        sa.Column("paths", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.execute(
        "UPDATE guidesync_project_repositories SET paths = analysis_paths "
        "WHERE analysis_paths IS NOT NULL"
    )
    op.drop_column("guidesync_project_repositories", "cache_warnings")
    op.drop_column("guidesync_project_repositories", "current_commit")
    op.drop_column("guidesync_project_repositories", "local_path")
    op.drop_column("guidesync_project_repositories", "cache_status")
    op.drop_column("guidesync_project_repositories", "credential_ref")
    op.drop_column("guidesync_project_repositories", "analysis_paths")

    op.drop_column("guidesync_projects", "credential_ref")
    op.drop_column("guidesync_projects", "analysis_paths")
    op.drop_column("guidesync_projects", "knowledge_base_path")
    op.drop_column("guidesync_projects", "knowledge_base_ref")
    op.drop_column("guidesync_projects", "knowledge_base_repository_id")
    op.drop_column("guidesync_projects", "documentation_instructions")
    op.drop_column("guidesync_projects", "audience")
