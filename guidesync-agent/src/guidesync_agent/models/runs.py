from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Table, Text

from guidesync_agent.models.base import metadata

report_runs_table = Table(
    "guidesync_report_runs",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("status", String(32), nullable=False),
    Column("mode", String(64), nullable=True),
    Column("goal", Text, nullable=False),
    Column("audience", Text, nullable=False),
    Column("provider", String(64), nullable=True),
    Column("model", String(255), nullable=True),
    Column("task_interface_url", Text, nullable=True),
    Column("task_interface_auth_type", String(32), nullable=True),
    Column("screenshot_policy", String(32), nullable=False),
    Column("effective_model_configuration", JSON, nullable=True),
    Column("project_profile_snapshot_id", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("error_message", Text, nullable=True),
    Column("request_snapshot", JSON, nullable=False),
    Column("result_snapshot", JSON, nullable=False),
    Column("publication_snapshot", JSON, nullable=True),
    Column("filters", JSON, nullable=False),
)

run_ui_auth_secrets_table = Table(
    "guidesync_run_ui_auth_secrets",
    metadata,
    Column(
        "run_id",
        String(128),
        ForeignKey("guidesync_report_runs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("auth_type", String(32), nullable=False),
    Column("auth_secret", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

run_events_table = Table(
    "guidesync_report_run_events",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("stage", String(128), nullable=True),
    Column("message", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

run_artifacts_table = Table(
    "guidesync_report_artifacts",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("artifact_type", String(64), nullable=False),
    Column("uri", Text, nullable=False),
    Column("content_type", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

evidence_items_table = Table(
    "guidesync_evidence_items",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("source_type", String(64), nullable=False),
    Column("source_ref", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("score", JSON, nullable=True),
    Column("metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

change_classifications_table = Table(
    "guidesync_change_classifications",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("source_ref", Text, nullable=False),
    Column("category", String(128), nullable=False),
    Column("confidence", JSON, nullable=True),
    Column("method", String(128), nullable=False),
    Column("explanation", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

screenshots_table = Table(
    "guidesync_screenshots",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=False),
    Column("repository_id", String(128), nullable=True),
    Column("url_or_route", Text, nullable=False),
    Column("artifact_uri", Text, nullable=False),
    Column("viewport", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

Index(
    "ix_guidesync_report_runs_status_created",
    report_runs_table.c.status,
    report_runs_table.c.created_at,
)
Index(
    "ix_guidesync_report_runs_project_updated",
    report_runs_table.c.project_id,
    report_runs_table.c.updated_at,
)
Index(
    "ix_guidesync_report_run_events_run_created",
    run_events_table.c.run_id,
    run_events_table.c.created_at,
)
Index("ix_guidesync_report_artifacts_run", run_artifacts_table.c.run_id)
Index("ix_guidesync_evidence_items_run", evidence_items_table.c.run_id)
Index("ix_guidesync_change_classifications_run", change_classifications_table.c.run_id)
Index("ix_guidesync_screenshots_run", screenshots_table.c.run_id)
