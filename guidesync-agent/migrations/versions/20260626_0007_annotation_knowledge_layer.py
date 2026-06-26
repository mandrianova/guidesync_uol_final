"""add annotation-first knowledge layer

Revision ID: 20260626_0007
Revises: 20260625_0006
Create Date: 2026-06-26 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_0007"
down_revision: str | None = "20260625_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    ensure_project_profile_taxonomy_columns(inspector)
    ensure_annotation_tables(inspector)


def downgrade() -> None:
    drop_index_if_exists(
        "ix_guidesync_knowledge_annotation_edges_target",
        "guidesync_knowledge_annotation_edges",
    )
    drop_index_if_exists(
        "ix_guidesync_knowledge_concepts_project_value",
        "guidesync_knowledge_concepts",
    )
    drop_index_if_exists(
        "ix_guidesync_knowledge_annotations_kind_value",
        "guidesync_knowledge_annotations",
    )
    drop_index_if_exists(
        "ix_guidesync_knowledge_annotations_source",
        "guidesync_knowledge_annotations",
    )
    drop_index_if_exists(
        "ix_guidesync_knowledge_annotation_runs_source",
        "guidesync_knowledge_annotation_runs",
    )
    drop_index_if_exists(
        "ix_guidesync_knowledge_annotation_runs_project",
        "guidesync_knowledge_annotation_runs",
    )
    drop_table_if_exists("guidesync_knowledge_annotation_edges")
    drop_table_if_exists("guidesync_knowledge_annotations")
    drop_table_if_exists("guidesync_knowledge_concepts")
    drop_table_if_exists("guidesync_knowledge_annotation_runs")

    profile_columns = table_columns("guidesync_project_profiles")
    with op.batch_alter_table("guidesync_project_profiles") as batch_op:
        if "profile_evidence" in profile_columns:
            batch_op.drop_column("profile_evidence")
        if "taxonomy" in profile_columns:
            batch_op.drop_column("taxonomy")


def ensure_project_profile_taxonomy_columns(inspector: sa.Inspector) -> None:
    if not inspector.has_table("guidesync_project_profiles"):
        return
    columns = {column["name"] for column in inspector.get_columns("guidesync_project_profiles")}
    with op.batch_alter_table("guidesync_project_profiles") as batch_op:
        if "taxonomy" not in columns:
            batch_op.add_column(sa.Column("taxonomy", sa.JSON(), nullable=True))
        if "profile_evidence" not in columns:
            batch_op.add_column(sa.Column("profile_evidence", sa.JSON(), nullable=True))
    op.execute(
        sa.text("UPDATE guidesync_project_profiles SET taxonomy = '{}' WHERE taxonomy IS NULL")
    )
    op.execute(
        sa.text(
            "UPDATE guidesync_project_profiles "
            "SET profile_evidence = '[]' WHERE profile_evidence IS NULL"
        )
    )
    with op.batch_alter_table("guidesync_project_profiles") as batch_op:
        batch_op.alter_column("taxonomy", nullable=False)
        batch_op.alter_column("profile_evidence", nullable=False)


def ensure_annotation_tables(inspector: sa.Inspector) -> None:
    if not inspector.has_table("guidesync_knowledge_annotation_runs"):
        op.create_table(
            "guidesync_knowledge_annotation_runs",
            sa.Column("id", sa.String(length=128), primary_key=True),
            sa.Column("project_id", sa.String(length=128), nullable=True),
            sa.Column("source_type", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("source_path", sa.Text(), nullable=True),
            sa.Column("taxonomy_version", sa.String(length=128), nullable=True),
            sa.Column("method_id", sa.String(length=128), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("source_commit", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("warnings", sa.JSON(), nullable=False),
            sa.Column("summary", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        )
    else:
        ensure_annotation_run_columns(inspector)

    if not inspector.has_table("guidesync_knowledge_concepts"):
        op.create_table(
            "guidesync_knowledge_concepts",
            sa.Column("id", sa.String(length=128), primary_key=True),
            sa.Column("project_id", sa.String(length=128), nullable=True),
            sa.Column("taxonomy_version", sa.String(length=128), nullable=True),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("canonical_value", sa.Text(), nullable=False),
            sa.Column("aliases", sa.JSON(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
        )

    if not inspector.has_table("guidesync_knowledge_annotations"):
        op.create_table(
            "guidesync_knowledge_annotations",
            sa.Column("id", sa.String(length=128), primary_key=True),
            sa.Column("run_id", sa.String(length=128), nullable=False),
            sa.Column("project_id", sa.String(length=128), nullable=True),
            sa.Column("source_type", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=False),
            sa.Column("source_path", sa.Text(), nullable=True),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("normalized_value", sa.Text(), nullable=False),
            sa.Column("canonical_value", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["guidesync_knowledge_annotation_runs.id"]),
        )

    if not inspector.has_table("guidesync_knowledge_annotation_edges"):
        op.create_table(
            "guidesync_knowledge_annotation_edges",
            sa.Column("id", sa.String(length=128), primary_key=True),
            sa.Column("project_id", sa.String(length=128), nullable=True),
            sa.Column("source_type", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=False),
            sa.Column("source_path", sa.Text(), nullable=True),
            sa.Column("edge_type", sa.String(length=64), nullable=False),
            sa.Column("target_type", sa.String(length=64), nullable=False),
            sa.Column("target_value", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("evidence_ref", sa.Text(), nullable=True),
            sa.Column("annotation_run_id", sa.String(length=128), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["guidesync_projects.id"]),
            sa.ForeignKeyConstraint(
                ["annotation_run_id"],
                ["guidesync_knowledge_annotation_runs.id"],
            ),
        )
    create_indexes()


def ensure_annotation_run_columns(inspector: sa.Inspector) -> None:
    columns = {
        column["name"] for column in inspector.get_columns("guidesync_knowledge_annotation_runs")
    }
    with op.batch_alter_table("guidesync_knowledge_annotation_runs") as batch_op:
        if "source_id" not in columns:
            batch_op.add_column(sa.Column("source_id", sa.String(length=128), nullable=True))
        if "source_path" not in columns:
            batch_op.add_column(sa.Column("source_path", sa.Text(), nullable=True))


def create_indexes() -> None:
    create_index_if_missing(
        "ix_guidesync_knowledge_annotation_runs_project",
        "guidesync_knowledge_annotation_runs",
        ["project_id"],
    )
    create_index_if_missing(
        "ix_guidesync_knowledge_annotation_runs_source",
        "guidesync_knowledge_annotation_runs",
        ["project_id", "source_type", "source_id"],
    )
    create_index_if_missing(
        "ix_guidesync_knowledge_annotations_source",
        "guidesync_knowledge_annotations",
        ["project_id", "source_type", "source_id"],
    )
    create_index_if_missing(
        "ix_guidesync_knowledge_annotations_kind_value",
        "guidesync_knowledge_annotations",
        ["project_id", "kind", "normalized_value"],
    )
    create_index_if_missing(
        "ix_guidesync_knowledge_concepts_project_value",
        "guidesync_knowledge_concepts",
        ["project_id", "kind", "canonical_value"],
    )
    create_index_if_missing(
        "ix_guidesync_knowledge_annotation_edges_target",
        "guidesync_knowledge_annotation_edges",
        ["project_id", "edge_type", "target_value"],
    )


def create_index_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns)


def drop_index_if_exists(name: str, table_name: str) -> None:
    if table_name not in table_names():
        return
    existing = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)


def drop_table_if_exists(table_name: str) -> None:
    if table_name in table_names():
        op.drop_table(table_name)


def table_columns(table_name: str) -> set[str]:
    if table_name not in table_names():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())
