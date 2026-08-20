"""Query traces

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "query_traces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("refused", sa.Boolean(), nullable=False),
        sa.Column("refusal_reason", sa.String(64), nullable=True),
        # Ranks and scores per retrieved chunk, so a ranking can be inspected
        # without re-running retrieval against a corpus that may have changed.
        sa.Column("retrieved", JSONB(), nullable=False),
        sa.Column("citations", ARRAY(sa.Integer()), nullable=False),
        sa.Column("invalid_citations", ARRAY(sa.Integer()), nullable=False),
        sa.Column("filters_applied", sa.String(500), nullable=False),
        sa.Column("top_similarity", sa.Float(), nullable=True),
        sa.Column("excerpt_count", sa.Integer(), nullable=False),
        sa.Column("context_tokens", sa.Integer(), nullable=False),
        sa.Column("retrieval_ms", sa.Integer(), nullable=False),
        sa.Column("generation_ms", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("generation_model", sa.String(128), nullable=False),
    )
    op.create_index("ix_query_traces_created_at", "query_traces", ["created_at"])


def downgrade() -> None:
    op.drop_table("query_traces")
