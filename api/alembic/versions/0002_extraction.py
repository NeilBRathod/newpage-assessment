"""Extraction: summaries, decisions, action items

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _grounding_columns() -> list[sa.Column]:
    """Where an extracted record claims to come from.

    A null `utterance_seq` means the model produced a quote that is not in the
    transcript — the clearest fabrication signal available, so it is recorded
    rather than discarded.
    """
    return [
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("utterance_seq", sa.Integer(), nullable=True),
        sa.Column("speaker", sa.String(200), nullable=True),
        sa.Column("start_s", sa.Float(), nullable=True),
    ]


def upgrade() -> None:
    op.add_column("meetings", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "meetings", sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "meeting_id",
            UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        *_grounding_columns(),
    )
    op.create_index("ix_decisions_meeting_id", "decisions", ["meeting_id"])

    op.create_table(
        "action_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "meeting_id",
            UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(200), nullable=False),
        # Free text, not a date: meetings say "by Friday" and "before GA", and
        # coercing that to a date would invent precision nobody stated.
        sa.Column("due", sa.String(200), nullable=True),
        *_grounding_columns(),
    )
    op.create_index("ix_action_items_meeting_id", "action_items", ["meeting_id"])
    op.create_index("ix_action_items_owner", "action_items", ["owner"])


def downgrade() -> None:
    op.drop_table("action_items")
    op.drop_table("decisions")
    op.drop_column("meetings", "extracted_at")
    op.drop_column("meetings", "summary")
