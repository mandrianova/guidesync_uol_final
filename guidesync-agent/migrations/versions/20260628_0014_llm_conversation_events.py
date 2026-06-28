"""add llm conversation event history

Revision ID: 20260628_0014
Revises: 20260627_0013
Create Date: 2026-06-28 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260628_0014"
down_revision: str | None = "20260627_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("guidesync_llm_conversation_events"):
        return
    op.create_table(
        "guidesync_llm_conversation_events",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_kind", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=255), nullable=True),
        sa.Column("tool_name", sa.String(length=255), nullable=True),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("result_status", sa.String(length=64), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("artifact_refs", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["guidesync_llm_conversations.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_guidesync_llm_conversation_events_conversation",
        "guidesync_llm_conversation_events",
        ["conversation_id"],
    )
    op.create_index(
        "uq_guidesync_llm_conversation_events_sequence",
        "guidesync_llm_conversation_events",
        ["conversation_id", "sequence"],
        unique=True,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("guidesync_llm_conversation_events"):
        return
    op.drop_index(
        "uq_guidesync_llm_conversation_events_sequence",
        table_name="guidesync_llm_conversation_events",
    )
    op.drop_index(
        "ix_guidesync_llm_conversation_events_conversation",
        table_name="guidesync_llm_conversation_events",
    )
    op.drop_table("guidesync_llm_conversation_events")
