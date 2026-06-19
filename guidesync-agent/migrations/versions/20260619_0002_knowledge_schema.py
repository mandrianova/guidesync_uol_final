"""add knowledge graph schema

Revision ID: 20260619_0002
Revises: 20260613_0001
Create Date: 2026-06-19 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0002"
down_revision: str | None = "20260613_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guidesync_knowledge_index_runs",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guidesync_knowledge_index_runs_project",
        "guidesync_knowledge_index_runs",
        ["project_id"],
    )
    op.create_table(
        "guidesync_knowledge_nodes",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("repo", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("qualified_name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guidesync_knowledge_nodes_project_kind",
        "guidesync_knowledge_nodes",
        ["project_id", "kind"],
    )
    op.create_index(
        "ix_guidesync_knowledge_nodes_path",
        "guidesync_knowledge_nodes",
        ["path"],
    )
    op.create_table(
        "guidesync_knowledge_edges",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("source_node_id", sa.String(length=128), nullable=False),
        sa.Column("target_node_id", sa.String(length=128), nullable=False),
        sa.Column("edge_type", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        sa.ForeignKeyConstraint(["source_node_id"], ["guidesync_knowledge_nodes.id"]),
        sa.ForeignKeyConstraint(["target_node_id"], ["guidesync_knowledge_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guidesync_knowledge_edges_project",
        "guidesync_knowledge_edges",
        ["project_id"],
    )
    op.create_index(
        "ix_guidesync_knowledge_edges_source",
        "guidesync_knowledge_edges",
        ["source_node_id"],
    )
    op.create_index(
        "ix_guidesync_knowledge_edges_target",
        "guidesync_knowledge_edges",
        ["target_node_id"],
    )
    op.create_table(
        "guidesync_knowledge_chunks",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("repo", sa.String(length=255), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["guidesync_knowledge_nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guidesync_knowledge_chunks_project",
        "guidesync_knowledge_chunks",
        ["project_id"],
    )
    op.create_index(
        "ix_guidesync_knowledge_chunks_node",
        "guidesync_knowledge_chunks",
        ["node_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_guidesync_knowledge_chunks_node", table_name="guidesync_knowledge_chunks")
    op.drop_index("ix_guidesync_knowledge_chunks_project", table_name="guidesync_knowledge_chunks")
    op.drop_table("guidesync_knowledge_chunks")
    op.drop_index("ix_guidesync_knowledge_edges_target", table_name="guidesync_knowledge_edges")
    op.drop_index("ix_guidesync_knowledge_edges_source", table_name="guidesync_knowledge_edges")
    op.drop_index("ix_guidesync_knowledge_edges_project", table_name="guidesync_knowledge_edges")
    op.drop_table("guidesync_knowledge_edges")
    op.drop_index("ix_guidesync_knowledge_nodes_path", table_name="guidesync_knowledge_nodes")
    op.drop_index(
        "ix_guidesync_knowledge_nodes_project_kind",
        table_name="guidesync_knowledge_nodes",
    )
    op.drop_table("guidesync_knowledge_nodes")
    op.drop_index(
        "ix_guidesync_knowledge_index_runs_project",
        table_name="guidesync_knowledge_index_runs",
    )
    op.drop_table("guidesync_knowledge_index_runs")
