"""add evaluation experiment scorecards

Revision ID: 20260728_0016
Revises: 20260628_0015
Create Date: 2026-07-28 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0016"
down_revision: str | None = "20260628_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guidesync_evaluation_experiments",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("manifest_checksum", sa.String(length=64), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guidesync_evaluation_experiments_project_updated",
        "guidesync_evaluation_experiments",
        ["project_id", "updated_at"],
    )
    op.create_table(
        "guidesync_evaluation_runs",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("experiment_id", sa.String(length=128), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("condition_id", sa.String(length=128), nullable=False),
        sa.Column("repetition", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("case_checksum", sa.String(length=64), nullable=False),
        sa.Column("condition_checksum", sa.String(length=64), nullable=False),
        sa.Column("configuration_checksum", sa.String(length=64), nullable=False),
        sa.Column("experiment_checksum", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["guidesync_evaluation_experiments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id",
            "case_id",
            "condition_id",
            "repetition",
            name="uq_guidesync_evaluation_run_pair",
        ),
    )
    op.create_index(
        "ix_guidesync_evaluation_runs_experiment_case",
        "guidesync_evaluation_runs",
        ["experiment_id", "case_id"],
    )
    op.create_index(
        "ix_guidesync_evaluation_runs_experiment_condition_status",
        "guidesync_evaluation_runs",
        ["experiment_id", "condition_id", "status"],
    )
    op.create_table(
        "guidesync_evaluation_comparisons",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("experiment_id", sa.String(length=128), nullable=False),
        sa.Column("full_condition_id", sa.String(length=128), nullable=False),
        sa.Column("ablation_condition_id", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["guidesync_evaluation_experiments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id",
            "ablation_condition_id",
            name="uq_guidesync_evaluation_comparison",
        ),
    )
    op.create_index(
        "ix_guidesync_evaluation_comparisons_experiment",
        "guidesync_evaluation_comparisons",
        ["experiment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_guidesync_evaluation_comparisons_experiment",
        table_name="guidesync_evaluation_comparisons",
    )
    op.drop_table("guidesync_evaluation_comparisons")
    op.drop_index(
        "ix_guidesync_evaluation_runs_experiment_condition_status",
        table_name="guidesync_evaluation_runs",
    )
    op.drop_index(
        "ix_guidesync_evaluation_runs_experiment_case",
        table_name="guidesync_evaluation_runs",
    )
    op.drop_table("guidesync_evaluation_runs")
    op.drop_index(
        "ix_guidesync_evaluation_experiments_project_updated",
        table_name="guidesync_evaluation_experiments",
    )
    op.drop_table("guidesync_evaluation_experiments")
