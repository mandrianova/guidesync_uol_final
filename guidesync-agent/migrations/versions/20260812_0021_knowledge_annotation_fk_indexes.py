"""index knowledge annotation foreign keys

Revision ID: 20260812_0021
Revises: 20260811_0020
Create Date: 2026-08-12 05:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260812_0021"
down_revision: str | None = "20260811_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_guidesync_knowledge_annotations_run",
        "guidesync_knowledge_annotations",
        ["run_id"],
    )
    op.create_index(
        "ix_guidesync_knowledge_annotation_edges_run",
        "guidesync_knowledge_annotation_edges",
        ["annotation_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_guidesync_knowledge_annotation_edges_run",
        table_name="guidesync_knowledge_annotation_edges",
    )
    op.drop_index(
        "ix_guidesync_knowledge_annotations_run",
        table_name="guidesync_knowledge_annotations",
    )
