from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text

from guidesync_agent.models.base import metadata

project_workflow_tasks_table = Table(
    "guidesync_project_workflow_tasks",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=False),
    Column("kind", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("depends_on_task_ids", JSON, nullable=False),
    Column("dedupe_key", Text, nullable=True),
    Column("requested_by", String(32), nullable=False),
    Column("reason", Text, nullable=False),
    Column("input", JSON, nullable=False),
    Column("result", JSON, nullable=True),
    Column("error_message", Text, nullable=True),
    Column("warnings", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

Index(
    "ix_guidesync_project_workflow_tasks_project_sequence",
    project_workflow_tasks_table.c.project_id,
    project_workflow_tasks_table.c.sequence,
)
Index(
    "ix_guidesync_project_workflow_tasks_project_status",
    project_workflow_tasks_table.c.project_id,
    project_workflow_tasks_table.c.status,
)
Index(
    "ix_guidesync_project_workflow_tasks_dedupe",
    project_workflow_tasks_table.c.project_id,
    project_workflow_tasks_table.c.dedupe_key,
)
