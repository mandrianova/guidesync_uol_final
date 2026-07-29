from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from guidesync_agent.models.base import metadata

evaluation_json = JSON().with_variant(JSONB(), "postgresql")

evaluation_experiments_table = Table(
    "guidesync_evaluation_experiments",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=False),
    Column("manifest_checksum", String(64), nullable=False),
    Column("manifest", evaluation_json, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

evaluation_runs_table = Table(
    "guidesync_evaluation_runs",
    metadata,
    Column("id", String(255), primary_key=True),
    Column(
        "experiment_id",
        String(128),
        ForeignKey("guidesync_evaluation_experiments.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("case_id", String(128), nullable=False),
    Column("condition_id", String(128), nullable=False),
    Column("repetition", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("case_checksum", String(64), nullable=False),
    Column("condition_checksum", String(64), nullable=False),
    Column("configuration_checksum", String(64), nullable=False),
    Column("experiment_checksum", String(64), nullable=False),
    Column("payload", evaluation_json, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "experiment_id",
        "case_id",
        "condition_id",
        "repetition",
        name="uq_guidesync_evaluation_run_pair",
    ),
)

evaluation_comparisons_table = Table(
    "guidesync_evaluation_comparisons",
    metadata,
    Column("id", String(128), primary_key=True),
    Column(
        "experiment_id",
        String(128),
        ForeignKey("guidesync_evaluation_experiments.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("full_condition_id", String(128), nullable=False),
    Column("ablation_condition_id", String(128), nullable=False),
    Column("payload", evaluation_json, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "experiment_id",
        "ablation_condition_id",
        name="uq_guidesync_evaluation_comparison",
    ),
)

Index(
    "ix_guidesync_evaluation_experiments_project_updated",
    evaluation_experiments_table.c.project_id,
    evaluation_experiments_table.c.updated_at,
)
Index(
    "ix_guidesync_evaluation_runs_experiment_case",
    evaluation_runs_table.c.experiment_id,
    evaluation_runs_table.c.case_id,
)
Index(
    "ix_guidesync_evaluation_runs_experiment_condition_status",
    evaluation_runs_table.c.experiment_id,
    evaluation_runs_table.c.condition_id,
    evaluation_runs_table.c.status,
)
Index(
    "ix_guidesync_evaluation_comparisons_experiment",
    evaluation_comparisons_table.c.experiment_id,
)
