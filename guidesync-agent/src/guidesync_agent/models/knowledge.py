from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)

from guidesync_agent.models.base import metadata

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

knowledge_annotation_runs_table = Table(
    "guidesync_knowledge_annotation_runs",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("source_type", String(64), nullable=False),
    Column("source_id", String(128), nullable=True),
    Column("source_path", Text, nullable=True),
    Column("taxonomy_version", String(128), nullable=True),
    Column("method_id", String(128), nullable=False),
    Column("content_hash", String(64), nullable=True),
    Column("source_commit", String(64), nullable=True),
    Column("status", String(32), nullable=False),
    Column("warnings", JSON, nullable=False),
    Column("summary", JSON, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

knowledge_annotations_table = Table(
    "guidesync_knowledge_annotations",
    metadata,
    Column("id", String(128), primary_key=True),
    Column(
        "run_id",
        String(128),
        ForeignKey("guidesync_knowledge_annotation_runs.id"),
        nullable=False,
    ),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("source_type", String(64), nullable=False),
    Column("source_id", String(128), nullable=False),
    Column("source_path", Text, nullable=True),
    Column("kind", String(64), nullable=False),
    Column("value", Text, nullable=False),
    Column("normalized_value", Text, nullable=False),
    Column("canonical_value", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("source", String(64), nullable=False),
    Column("evidence", JSON, nullable=False),
    Column("metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

knowledge_concepts_table = Table(
    "guidesync_knowledge_concepts",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("taxonomy_version", String(128), nullable=True),
    Column("kind", String(64), nullable=False),
    Column("canonical_value", Text, nullable=False),
    Column("aliases", JSON, nullable=False),
    Column("metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

knowledge_annotation_edges_table = Table(
    "guidesync_knowledge_annotation_edges",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("project_id", String(128), ForeignKey("guidesync_projects.id"), nullable=True),
    Column("source_type", String(64), nullable=False),
    Column("source_id", String(128), nullable=False),
    Column("source_path", Text, nullable=True),
    Column("edge_type", String(64), nullable=False),
    Column("target_type", String(64), nullable=False),
    Column("target_value", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("evidence_ref", Text, nullable=True),
    Column(
        "annotation_run_id",
        String(128),
        ForeignKey("guidesync_knowledge_annotation_runs.id"),
        nullable=False,
    ),
    Column("metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

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
Index(
    "ix_guidesync_knowledge_annotation_runs_project",
    knowledge_annotation_runs_table.c.project_id,
)
Index(
    "ix_guidesync_knowledge_annotation_runs_source",
    knowledge_annotation_runs_table.c.project_id,
    knowledge_annotation_runs_table.c.source_type,
    knowledge_annotation_runs_table.c.source_id,
)
Index(
    "ix_guidesync_knowledge_annotations_source",
    knowledge_annotations_table.c.project_id,
    knowledge_annotations_table.c.source_type,
    knowledge_annotations_table.c.source_id,
)
Index(
    "ix_guidesync_knowledge_annotations_kind_value",
    knowledge_annotations_table.c.project_id,
    knowledge_annotations_table.c.kind,
    knowledge_annotations_table.c.normalized_value,
)
Index(
    "ix_guidesync_knowledge_concepts_project_value",
    knowledge_concepts_table.c.project_id,
    knowledge_concepts_table.c.kind,
    knowledge_concepts_table.c.canonical_value,
)
Index(
    "ix_guidesync_knowledge_annotation_edges_target",
    knowledge_annotation_edges_table.c.project_id,
    knowledge_annotation_edges_table.c.edge_type,
    knowledge_annotation_edges_table.c.target_value,
)
