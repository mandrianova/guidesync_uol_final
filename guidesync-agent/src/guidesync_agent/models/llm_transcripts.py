from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text

from guidesync_agent.models.base import metadata

llm_conversations_table = Table(
    "guidesync_llm_conversations",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("run_id", String(128), ForeignKey("guidesync_report_runs.id"), nullable=True),
    Column("workflow_task_id", String(128), nullable=True),
    Column("parent_conversation_id", String(128), nullable=True),
    Column("model_call_id", String(128), nullable=True),
    Column("model_role", String(64), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model", String(255), nullable=False),
    Column("endpoint_type", String(64), nullable=True),
    Column("conversation_id", String(255), nullable=False),
    Column("turn_index", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("message_count", Integer, nullable=False),
    Column("tool_call_count", Integer, nullable=False),
    Column("token_ledger_entry_id", String(128), nullable=True),
    Column("transcript_artifact_ref", Text, nullable=True),
    Column("full_history_artifact_ref", Text, nullable=True),
    Column("redaction_status", String(32), nullable=False),
    Column("prompt_metadata", JSON, nullable=False),
    Column("provider_metadata", JSON, nullable=False),
    Column("endpoint_metadata", JSON, nullable=False),
    Column("model_settings", JSON, nullable=False),
    Column("message_stats", JSON, nullable=False),
    Column("tool_summary", JSON, nullable=False),
    Column("redaction_metadata", JSON, nullable=False),
    Column("diagnostics", JSON, nullable=False),
)

Index("ix_guidesync_llm_conversations_run", llm_conversations_table.c.run_id)
Index(
    "ix_guidesync_llm_conversations_workflow_task",
    llm_conversations_table.c.workflow_task_id,
)
Index("ix_guidesync_llm_conversations_model_call", llm_conversations_table.c.model_call_id)
