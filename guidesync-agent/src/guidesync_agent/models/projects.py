from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)

from guidesync_agent.models.base import metadata

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
    Column("roles", JSON, nullable=False),
    Column("is_default", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
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

project_profiles_table = Table(
    "guidesync_project_profiles",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("version", Integer, nullable=False),
    Column("prompt_version", String(128), nullable=False),
    Column("summary", Text, nullable=False),
    Column("project_description", Text, nullable=False),
    Column("project_structure", JSON, nullable=False),
    Column("architecture", JSON, nullable=False),
    Column("core_concepts", JSON, nullable=False),
    Column("workflows", JSON, nullable=False),
    Column("key_terms", JSON, nullable=False),
    Column("agent_context", Text, nullable=False),
    Column("taxonomy", JSON, nullable=False),
    Column("profile_evidence", JSON, nullable=False),
    Column("repository_map", JSON, nullable=False),
    Column("source_refs", JSON, nullable=False),
    Column("warnings", JSON, nullable=False),
    Column("uncertainty_notes", JSON, nullable=False),
    Column("artifact_uris", JSON, nullable=False),
    Column("model_metadata", JSON, nullable=False),
    Column("tool_trace_refs", JSON, nullable=False),
    Column("validation_findings", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("error_message", Text, nullable=True),
)

Index("ix_guidesync_project_repositories_project", project_repositories_table.c.project_id)
Index("ix_guidesync_project_documentation_project", project_documentation_table.c.project_id)
Index(
    "ix_guidesync_project_profiles_project_version",
    project_profiles_table.c.project_id,
    project_profiles_table.c.version,
)
Index("ix_guidesync_model_profiles_project", model_profiles_table.c.project_id)
