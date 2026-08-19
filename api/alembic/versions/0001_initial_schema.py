"""Initial schema: meetings, utterances, chunks

Revision ID: 0001
Revises:
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # db/init.sql already does this on a container's first boot, but a database
    # created any other way needs it too, and it must be idempotent either way.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "meetings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("meeting_date", sa.Date(), nullable=True),
        sa.Column("source_filename", sa.String(500), nullable=False),
        sa.Column("source_format", sa.String(32), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("participants", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("utterance_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Unique so the same transcript cannot be stored twice under two ids, which
    # would double-count its chunks in every later retrieval.
    op.create_index("ix_meetings_content_hash", "meetings", ["content_hash"], unique=True)

    op.create_table(
        "utterances",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "meeting_id",
            UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(200), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.UniqueConstraint("meeting_id", "seq", name="uq_utterance_meeting_seq"),
    )
    op.create_index("ix_utterances_meeting_id", "utterances", ["meeting_id"])
    op.create_index("ix_utterances_speaker", "utterances", ["speaker"])

    op.create_table(
        "chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "meeting_id",
            UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("context_header", sa.Text(), nullable=False),
        sa.Column("speakers", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("utterance_seqs", sa.ARRAY(sa.Integer()), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        # Dimensions must match the embedding model. Changing models means a
        # migration here and a full re-embed — vectors from different models are
        # not comparable, and mixing them fails quietly rather than loudly.
        sa.Column("embedding", Vector(768), nullable=True),
        # Maintained by Postgres rather than the application, so it can never
        # drift out of step with `text`.
        sa.Column(
            "tsv",
            TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
        ),
        sa.UniqueConstraint("meeting_id", "seq", name="uq_chunk_meeting_seq"),
    )
    op.create_index("ix_chunks_meeting_id", "chunks", ["meeting_id"])
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    # HNSW rather than IVFFlat: it needs no training step and no rebuild as rows
    # are added, which matters when the corpus grows one meeting at a time.
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("utterances")
    op.drop_table("meetings")
