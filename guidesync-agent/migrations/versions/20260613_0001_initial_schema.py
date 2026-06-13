"""initial guidesync schema

Revision ID: 20260613_0001
Revises:
Create Date: 2026-06-13 12:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260613_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guidesync_projects",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
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
    op.create_index(
        "ix_guidesync_project_repositories_project",
        "guidesync_project_repositories",
        ["project_id"],
    )
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
    op.create_index(
        "ix_guidesync_project_documentation_project",
        "guidesync_project_documentation",
        ["project_id"],
    )
    op.create_table(
        "guidesync_model_profiles",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("api_key_secret_ref", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guidesync_model_profiles_project", "guidesync_model_profiles", ["project_id"]
    )
    op.create_table(
        "guidesync_report_runs",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("model_profile_id", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        sa.ForeignKeyConstraint(["model_profile_id"], ["guidesync_model_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guidesync_report_runs_status_created",
        "guidesync_report_runs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_guidesync_report_runs_project_updated",
        "guidesync_report_runs",
        ["project_id", "updated_at"],
    )
    op.create_table(
        "guidesync_report_run_events",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=128), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["guidesync_report_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guidesync_report_run_events_run_created",
        "guidesync_report_run_events",
        ["run_id", "created_at"],
    )
    op.create_table(
        "guidesync_report_artifacts",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["guidesync_report_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guidesync_report_artifacts_run", "guidesync_report_artifacts", ["run_id"])
    op.create_table(
        "guidesync_evidence_items",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("score", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["guidesync_report_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guidesync_evidence_items_run", "guidesync_evidence_items", ["run_id"])
    op.create_table(
        "guidesync_change_classifications",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.JSON(), nullable=True),
        sa.Column("method", sa.String(length=128), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["guidesync_report_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guidesync_change_classifications_run",
        "guidesync_change_classifications",
        ["run_id"],
    )
    op.create_table(
        "guidesync_screenshots",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("repository_id", sa.String(length=128), nullable=True),
        sa.Column("url_or_route", sa.Text(), nullable=False),
        sa.Column("artifact_uri", sa.Text(), nullable=False),
        sa.Column("viewport", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["guidesync_report_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guidesync_screenshots_run", "guidesync_screenshots", ["run_id"])


def downgrade() -> None:
    op.drop_table("guidesync_screenshots")
    op.drop_table("guidesync_change_classifications")
    op.drop_table("guidesync_evidence_items")
    op.drop_table("guidesync_report_artifacts")
    op.drop_table("guidesync_report_run_events")
    op.drop_table("guidesync_report_runs")
    op.drop_table("guidesync_model_profiles")
    op.drop_table("guidesync_project_documentation")
    op.drop_table("guidesync_project_repositories")
    op.drop_table("guidesync_projects")
