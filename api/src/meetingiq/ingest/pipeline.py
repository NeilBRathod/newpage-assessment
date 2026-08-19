"""Ingestion: parse, chunk, embed, store.

Ingesting is idempotent on the raw file's sha256. Re-running `make seed` while
tuning retrieval should cost nothing, and it should be impossible to end up with
the same meeting stored twice under two ids — a duplicate would quietly skew
every retrieval afterwards by double-counting its chunks.
"""

import hashlib
import logging
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from meetingiq.config import Settings
from meetingiq.ingest.chunker import chunk_transcript
from meetingiq.ingest.parser import parse_transcript
from meetingiq.llm.base import EmbeddingKind, EmbeddingProvider
from meetingiq.models import Chunk, Meeting, Utterance

logger = logging.getLogger(__name__)

# Ollama processes an embedding batch sequentially; batching mainly saves HTTP
# round-trips. Small enough to keep memory flat on large transcripts.
_EMBED_BATCH_SIZE = 32


@dataclass(frozen=True, slots=True)
class IngestResult:
    meeting_id: str
    title: str
    utterance_count: int
    chunk_count: int
    skipped: bool
    duration_ms: int

    @property
    def summary(self) -> str:
        if self.skipped:
            return f"{self.title}: unchanged, skipped"
        return (
            f"{self.title}: {self.utterance_count} utterances, "
            f"{self.chunk_count} chunks in {self.duration_ms}ms"
        )


def content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def ingest_transcript(
    session: Session,
    *,
    raw_text: str,
    filename: str,
    settings: Settings,
    embedder: EmbeddingProvider,
    force: bool = False,
) -> IngestResult:
    """Ingest one transcript. Unchanged content is skipped unless `force`."""
    started = time.perf_counter()
    digest = content_hash(raw_text)

    existing = session.scalar(select(Meeting).where(Meeting.content_hash == digest))
    if existing and not force:
        logger.info("skipping unchanged transcript", extra={"source_filename": filename})
        return IngestResult(
            meeting_id=str(existing.id),
            title=existing.title,
            utterance_count=existing.utterance_count,
            chunk_count=existing.chunk_count,
            skipped=True,
            duration_ms=0,
        )
    if existing:
        # Cascades to utterances and chunks, so a forced re-ingest cannot leave
        # orphaned vectors from the previous chunking strategy behind.
        session.delete(existing)
        session.flush()

    transcript = parse_transcript(raw_text, filename=filename)
    chunks = chunk_transcript(
        transcript,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
    )

    meeting = Meeting(
        title=transcript.title,
        meeting_date=transcript.meeting_date,
        source_filename=filename,
        source_format=str(transcript.source_format),
        duration_s=transcript.duration_s,
        participants=transcript.participants,
        content_hash=digest,
        utterance_count=len(transcript.utterances),
        chunk_count=len(chunks),
    )
    session.add(meeting)
    session.flush()

    session.add_all(
        Utterance(
            meeting_id=meeting.id,
            seq=utterance.seq,
            speaker=utterance.speaker,
            start_s=utterance.start_s,
            end_s=utterance.end_s,
            text=utterance.text,
        )
        for utterance in transcript.utterances
    )

    # Chunk.embedding_input() applies EmbeddingGemma's document template, so
    # these are passed without further titles.
    inputs = [chunk.embedding_input(transcript.title) for chunk in chunks]
    vectors: list[list[float]] = []
    for start in range(0, len(inputs), _EMBED_BATCH_SIZE):
        vectors.extend(
            embedder.embed(inputs[start : start + _EMBED_BATCH_SIZE], kind=EmbeddingKind.DOCUMENT)
        )

    session.add_all(
        Chunk(
            meeting_id=meeting.id,
            seq=chunk.seq,
            text=chunk.text,
            context_header=chunk.context_header,
            speakers=chunk.speakers,
            start_s=chunk.start_s,
            end_s=chunk.end_s,
            utterance_seqs=chunk.utterance_seqs,
            token_estimate=chunk.token_estimate,
            embedding=vector,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    )
    session.commit()

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "ingested transcript",
        extra={
            "source_filename": filename,
            "meeting_id": str(meeting.id),
            "utterances": len(transcript.utterances),
            "chunks": len(chunks),
            "duration_ms": duration_ms,
        },
    )
    return IngestResult(
        meeting_id=str(meeting.id),
        title=transcript.title,
        utterance_count=len(transcript.utterances),
        chunk_count=len(chunks),
        skipped=False,
        duration_ms=duration_ms,
    )
