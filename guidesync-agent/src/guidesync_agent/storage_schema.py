from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

model_profiles_table = Table(
    "guidesync_model_profiles",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("name", String(255), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model", String(255), nullable=False),
    Column("base_url", Text, nullable=True),
    Column("api_key_secret_ref", Text, nullable=True),
    Column("timeout_seconds", Integer, nullable=False),
    Column("thinking", String(32), nullable=True),
    Column("is_default", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

report_runs_table = Table(
    "guidesync_report_runs",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("status", String(32), nullable=False),
    Column("mode", String(64), nullable=True),
    Column("goal", Text, nullable=False),
    Column("audience", Text, nullable=False),
    Column(
        "model_profile_id",
        String(128),
        ForeignKey("guidesync_model_profiles.id"),
        nullable=True,
    ),
    Column("provider", String(64), nullable=True),
    Column("model", String(255), nullable=True),
    Column("task_interface_url", Text, nullable=True),
    Column("screenshot_policy", String(32), nullable=False),
    Column("requested_model_settings", JSON, nullable=True),
    Column("effective_model_configuration", JSON, nullable=True),
    Column("project_profile_snapshot_id", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("error_message", Text, nullable=True),
    Column("request_snapshot", JSON, nullable=False),
    Column("result_snapshot", JSON, nullable=False),
    Column("filters", JSON, nullable=False),
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

projects_table = Table(
    "guidesync_projects",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("description", Text, nullable=True),
    Column("audience", String(64), nullable=False),
    Column("documentation_instructions", Text, nullable=False),
    Column("knowledge_base_repository_id", String(128), nullable=True),
    Column("knowledge_base_ref", String(255), nullable=True),
    Column("knowledge_base_path", Text, nullable=False),
    Column("analysis_paths", JSON, nullable=False),
    Column("credential_ref", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

project_repositories_table = Table(
    "guidesync_project_repositories",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=False),
    Column("name", String(255), nullable=False),
    Column("url", Text, nullable=False),
    Column("default_branch", String(255), nullable=True),
    Column("analysis_paths", JSON, nullable=False),
    Column("credential_ref", Text, nullable=True),
    Column("cache_status", String(32), nullable=False),
    Column("local_path", Text, nullable=True),
    Column("current_commit", String(64), nullable=True),
    Column("cache_warnings", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

project_documentation_table = Table(
    "guidesync_project_documentation",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=False),
    Column("name", String(255), nullable=False),
    Column("description", Text, nullable=True),
    Column("path", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

knowledge_index_runs_table = Table(
    "guidesync_knowledge_index_runs",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("status", String(32), nullable=False),
    Column("source_ref", Text, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("error_message", Text, nullable=True),
    Column("request_snapshot", JSON, nullable=False),
    Column("summary", JSON, nullable=False),
)

knowledge_nodes_table = Table(
    "guidesync_knowledge_nodes",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("repo", String(255), nullable=True),
    Column("kind", String(64), nullable=False),
    Column("name", String(255), nullable=False),
    Column("qualified_name", Text, nullable=False),
    Column("path", Text, nullable=True),
    Column("start_line", Integer, nullable=True),
    Column("end_line", Integer, nullable=True),
    Column("summary", Text, nullable=False),
    Column("content_hash", String(64), nullable=True),
    Column("metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

knowledge_edges_table = Table(
    "guidesync_knowledge_edges",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column(
        "source_node_id",
        String(128),
        ForeignKey("guidesync_knowledge_nodes.id"),
        nullable=False,
    ),
    Column(
        "target_node_id",
        String(128),
        ForeignKey("guidesync_knowledge_nodes.id"),
        nullable=False,
    ),
    Column("edge_type", String(64), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("evidence_ref", Text, nullable=True),
    Column("metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

knowledge_chunks_table = Table(
    "guidesync_knowledge_chunks",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("node_id", String(128), ForeignKey("guidesync_knowledge_nodes.id"), nullable=False),
    Column("repo", String(255), nullable=True),
    Column("path", Text, nullable=True),
    Column("heading", Text, nullable=True),
    Column("text", Text, nullable=False),
    Column("token_count", Integer, nullable=False),
    Column("metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

Index("ix_guidesync_project_repositories_project", project_repositories_table.c.project_id)
Index("ix_guidesync_project_documentation_project", project_documentation_table.c.project_id)
Index("ix_guidesync_model_profiles_project", model_profiles_table.c.project_id)
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
Index("ix_guidesync_knowledge_index_runs_project", knowledge_index_runs_table.c.project_id)
Index(
    "ix_guidesync_knowledge_nodes_project_kind",
    knowledge_nodes_table.c.project_id,
    knowledge_nodes_table.c.kind,
)
Index("ix_guidesync_knowledge_nodes_path", knowledge_nodes_table.c.path)
Index("ix_guidesync_knowledge_edges_project", knowledge_edges_table.c.project_id)
Index("ix_guidesync_knowledge_edges_source", knowledge_edges_table.c.source_node_id)
Index("ix_guidesync_knowledge_edges_target", knowledge_edges_table.c.target_node_id)
Index("ix_guidesync_knowledge_chunks_project", knowledge_chunks_table.c.project_id)
Index("ix_guidesync_knowledge_chunks_node", knowledge_chunks_table.c.node_id)
