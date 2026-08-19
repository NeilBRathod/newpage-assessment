"""Hybrid retrieval: dense vectors and full-text search, fused with RRF.

Dense retrieval alone is a poor fit for meeting talk. Transcripts are dense with
proper nouns that carry the meaning — project codenames, ticket ids, customer
and people names — and an embedding of "PAY-1042" is close to an embedding of
every other ticket id. Full-text search matches those exactly and is useless at
paraphrase. Each covers the other's blind spot.

They are fused with Reciprocal Rank Fusion rather than a weighted score blend.
Cosine similarity and ts_rank are not on comparable scales, and neither is
calibrated, so any weighting would be a magic number tuned to one corpus. RRF
throws the scores away and uses only rank, which needs no normalisation, no
tuning, and no reranker model.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import Float, Select, func, select
from sqlalchemy.orm import Session

from meetingiq.models import Chunk, Meeting
from meetingiq.retrieval.filters import RetrievalFilters

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    meeting_id: str
    meeting_title: str
    meeting_date: str | None
    seq: int
    text: str
    context_header: str
    speakers: list[str]
    start_s: float
    end_s: float
    utterance_seqs: list[int]

    # Kept separately so a trace can show *why* something ranked where it did.
    vector_rank: int | None
    text_rank: int | None
    vector_similarity: float | None
    rrf_score: float


def reciprocal_rank_fusion(ranked_lists: list[list[str]], *, k: int = 60) -> dict[str, float]:
    """Fuse ranked id lists into one score per id.

    score(d) = sum over lists of 1 / (k + rank(d)), rank starting at 1.

    `k` damps the influence of top positions: with k=60 the gap between rank 1
    and rank 2 is small, so a document both retrievers merely like beats one
    that a single retriever loves. That is the behaviour we want — agreement
    between two independent methods is better evidence than one strong opinion.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, identifier in enumerate(ranked, start=1):
            scores[identifier] = scores.get(identifier, 0.0) + 1.0 / (k + rank)
    return scores


def _apply_filters(statement: Select, filters: RetrievalFilters) -> Select:
    """Narrow candidates before ranking.

    Filtering in SQL rather than after retrieval matters: asking for the top 20
    and then discarding everything not from one meeting can leave nothing at all.
    """
    if filters.meeting_ids:
        statement = statement.where(Chunk.meeting_id.in_(filters.meeting_ids))
    if filters.speakers:
        # Chunk.speakers is an array; overlap means "mentions any of these".
        statement = statement.where(Chunk.speakers.overlap(filters.speakers))
    if filters.date_from:
        statement = statement.where(Meeting.meeting_date >= filters.date_from)
    if filters.date_to:
        statement = statement.where(Meeting.meeting_date <= filters.date_to)
    return statement


def _vector_candidates(
    session: Session, embedding: list[float], filters: RetrievalFilters, limit: int
) -> list[tuple[str, float]]:
    distance = Chunk.embedding.cosine_distance(embedding).label("distance")
    statement = (
        _apply_filters(
            select(Chunk.id, distance).join(Meeting, Meeting.id == Chunk.meeting_id), filters
        )
        .order_by(distance)
        .limit(limit)
    )
    return [(str(row.id), 1.0 - row.distance) for row in session.execute(statement)]


def _text_candidates(
    session: Session, query: str, filters: RetrievalFilters, limit: int
) -> list[str]:
    # websearch_to_tsquery tolerates ordinary human phrasing — quoted phrases,
    # "or", "-" — where plainto_tsquery would choke or silently drop operators.
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank(Chunk.tsv, tsquery).cast(Float).label("rank")
    statement = (
        _apply_filters(
            select(Chunk.id, rank).join(Meeting, Meeting.id == Chunk.meeting_id), filters
        )
        .where(Chunk.tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(limit)
    )
    return [str(row.id) for row in session.execute(statement)]


def hybrid_search(
    session: Session,
    *,
    query: str,
    embedding: list[float],
    filters: RetrievalFilters | None = None,
    candidates: int = 20,
    top_k: int = 8,
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Retrieve the best chunks for a query using both retrievers."""
    filters = filters or RetrievalFilters()

    vector_hits = _vector_candidates(session, embedding, filters, candidates)
    text_hits = _text_candidates(session, query, filters, candidates)

    vector_ids = [chunk_id for chunk_id, _ in vector_hits]
    similarity_by_id = dict(vector_hits)
    vector_rank_by_id = {chunk_id: rank for rank, chunk_id in enumerate(vector_ids, start=1)}
    text_rank_by_id = {chunk_id: rank for rank, chunk_id in enumerate(text_hits, start=1)}

    fused = reciprocal_rank_fusion([vector_ids, text_hits], k=rrf_k)
    if not fused:
        return []

    best_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:top_k]

    rows = session.execute(
        select(Chunk, Meeting.title, Meeting.meeting_date)
        .join(Meeting, Meeting.id == Chunk.meeting_id)
        .where(Chunk.id.in_(best_ids))
    ).all()
    by_id = {str(chunk.id): (chunk, title, meeting_date) for chunk, title, meeting_date in rows}

    results = []
    for chunk_id in best_ids:
        chunk, title, meeting_date = by_id[chunk_id]
        results.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                meeting_id=str(chunk.meeting_id),
                meeting_title=title,
                meeting_date=meeting_date.isoformat() if meeting_date else None,
                seq=chunk.seq,
                text=chunk.text,
                context_header=chunk.context_header,
                speakers=list(chunk.speakers),
                start_s=chunk.start_s,
                end_s=chunk.end_s,
                utterance_seqs=list(chunk.utterance_seqs),
                vector_rank=vector_rank_by_id.get(chunk_id),
                text_rank=text_rank_by_id.get(chunk_id),
                vector_similarity=similarity_by_id.get(chunk_id),
                rrf_score=fused[chunk_id],
            )
        )

    logger.info(
        "hybrid search complete",
        extra={
            "vector_hits": len(vector_ids),
            "text_hits": len(text_hits),
            "returned": len(results),
            "top_similarity": results[0].vector_similarity if results else None,
        },
    )
    return results
