from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text

from guidesync_agent.models.base import metadata

model_call_ledger_table = Table(
    "guidesync_model_call_ledger",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=True),
    Column("workflow_task_id", String(128), nullable=True),
    Column("parent_call_id", String(128), nullable=True),
    Column("role", String(64), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model", String(255), nullable=False),
    Column("model_profile_id", String(128), nullable=True),
    Column("endpoint_type", String(64), nullable=True),
    Column("base_url_host_hash", String(64), nullable=True),
    Column("deployment_id", String(128), nullable=True),
    Column("prompt_version", String(128), nullable=True),
    Column("structured_output_schema", String(128), nullable=True),
    Column("status", String(32), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("usage_source", String(32), nullable=False),
    Column("input_tokens", Integer, nullable=True),
    Column("output_tokens", Integer, nullable=True),
    Column("reasoning_tokens", Integer, nullable=True),
    Column("cached_input_tokens", Integer, nullable=True),
    Column("cache_write_tokens", Integer, nullable=True),
    Column("image_input_tokens", Integer, nullable=True),
    Column("image_input_units", Integer, nullable=True),
    Column("embedding_input_tokens", Integer, nullable=True),
    Column("tool_call_count", Integer, nullable=False),
    Column("model_turn_count", Integer, nullable=False),
    Column("context_compaction_input_tokens", Integer, nullable=True),
    Column("context_compaction_output_tokens", Integer, nullable=True),
    Column("provider_reported_total_tokens", Integer, nullable=True),
    Column("locally_estimated_total_tokens", Integer, nullable=True),
    Column("request_artifact_ref", Text, nullable=True),
    Column("response_artifact_ref", Text, nullable=True),
    Column("warnings", JSON, nullable=False),
    Column("error", Text, nullable=True),
)

Index("ix_guidesync_model_call_ledger_run", model_call_ledger_table.c.run_id)
Index("ix_guidesync_model_call_ledger_workflow_task", model_call_ledger_table.c.workflow_task_id)
Index("ix_guidesync_model_call_ledger_role", model_call_ledger_table.c.role)
