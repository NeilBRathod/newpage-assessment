"""Ingestion pipeline tests.

Integration tests: they need a real Postgres because the schema depends on
pgvector, ARRAY and a generated tsvector column. They skip when
MEETINGIQ_TEST_DATABASE_URL is unset.
"""

import pytest
from sqlalchemy import func, select

from meetingiq.config import Provider, Settings
from meetingiq.ingest.parser import TranscriptParseError
from meetingiq.ingest.pipeline import content_hash, ingest_transcript
from meetingiq.llm.fake import FakeEmbeddingProvider
from meetingiq.models import Chunk, Meeting, Utterance

TRANSCRIPT = """\
# Meeting: Relay Kickoff
# Date: 2026-04-07
# Duration: 00:20:00
# Participants: Priya Raman, Dana Osei

[00:00:05] Priya Raman: Let's talk about the ledger and whether it can take the load.
[00:00:31] Dana Osei: I benchmarked it. The p99 is four seconds, which is too slow.
[00:01:02] Priya Raman: Then we build a separate settlement service instead.
"""


@pytest.fixture
def ingest(db_session):
    settings = Settings(provider=Provider.FAKE)
    embedder = FakeEmbeddingProvider(settings.embedding_dimensions)

    def _ingest(raw_text: str = TRANSCRIPT, *, filename: str = "kickoff.txt", force: bool = False):
        return ingest_transcript(
            db_session,
            raw_text=raw_text,
            filename=filename,
            settings=settings,
            embedder=embedder,
            force=force,
        )

    return _ingest


def test_stores_meeting_utterances_and_chunks(ingest, db_session):
    result = ingest()

    assert not result.skipped
    assert result.utterance_count == 3

    meeting = db_session.scalar(select(Meeting))
    assert meeting.title == "Relay Kickoff"
    assert meeting.meeting_date.isoformat() == "2026-04-07"
    assert meeting.source_format == "bracketed"
    assert meeting.participants == ["Priya Raman", "Dana Osei"]
    assert db_session.scalar(select(func.count()).select_from(Utterance)) == 3


def test_every_chunk_is_embedded(ingest, db_session):
    ingest()

    chunks = db_session.scalars(select(Chunk)).all()
    assert chunks
    assert all(chunk.embedding is not None for chunk in chunks)
    assert all(len(chunk.embedding) == 768 for chunk in chunks)


def test_tsv_is_generated_by_the_database(ingest, db_session):
    """Maintained by Postgres, so it cannot drift out of step with the text."""
    ingest()

    tsv = db_session.scalar(select(Chunk.tsv))
    assert tsv is not None
    assert "ledger" in tsv


def test_reingesting_unchanged_content_is_a_no_op(ingest, db_session):
    first = ingest()
    second = ingest()

    assert second.skipped
    assert second.meeting_id == first.meeting_id
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 1


def test_force_replaces_rather_than_duplicates(ingest, db_session):
    first = ingest()
    second = ingest(force=True)

    assert not second.skipped
    assert second.meeting_id != first.meeting_id
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 1


def test_forced_reingest_leaves_no_orphaned_chunks(ingest, db_session):
    """Otherwise vectors from a previous chunking strategy stay in the index."""
    ingest()
    before = db_session.scalar(select(func.count()).select_from(Chunk))

    ingest(force=True)

    assert db_session.scalar(select(func.count()).select_from(Chunk)) == before


def test_edited_transcript_is_ingested_as_a_change(ingest, db_session):
    ingest()
    ingest(TRANSCRIPT + "[00:02:00] Dana Osei: One more thing.\n", filename="kickoff.txt")

    # A different hash is a different meeting; dedup is on content, not filename.
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 2


def test_chunks_reference_the_utterances_they_cover(ingest, db_session):
    """This is what lets a citation resolve back to an exact turn."""
    ingest()

    chunk = db_session.scalar(select(Chunk).order_by(Chunk.seq))
    utterance_seqs = set(
        db_session.scalars(select(Utterance.seq).where(Utterance.meeting_id == chunk.meeting_id))
    )
    assert set(chunk.utterance_seqs) <= utterance_seqs


def test_unparseable_transcript_raises(ingest):
    with pytest.raises(TranscriptParseError):
        ingest("no timestamps or speakers here at all")


def test_content_hash_is_stable_and_content_sensitive():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
