"""Reading query traces.

Every question the system has answered, with the retrieval that produced it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from meetingiq.db import get_session
from meetingiq.models import QueryTrace

router = APIRouter(prefix="/traces", tags=["traces"])


class TraceOut(BaseModel):
    id: str
    created_at: str
    question: str
    answer: str
    refused: bool
    refusal_reason: str | None
    retrieved: list[dict]
    citations: list[int]
    invalid_citations: list[int]
    filters_applied: str
    top_similarity: float | None
    excerpt_count: int
    context_tokens: int
    retrieval_ms: int
    generation_ms: int
    generation_model: str


class TraceStats(BaseModel):
    total: int
    refused: int
    with_invalid_citations: int
    p50_generation_ms: int | None
    p95_generation_ms: int | None


class TraceList(BaseModel):
    stats: TraceStats
    traces: list[TraceOut]


def _to_out(trace: QueryTrace) -> TraceOut:
    return TraceOut(
        id=str(trace.id),
        created_at=trace.created_at.isoformat(),
        question=trace.question,
        answer=trace.answer,
        refused=trace.refused,
        refusal_reason=trace.refusal_reason,
        retrieved=trace.retrieved,
        citations=list(trace.citations),
        invalid_citations=list(trace.invalid_citations),
        filters_applied=trace.filters_applied,
        top_similarity=trace.top_similarity,
        excerpt_count=trace.excerpt_count,
        context_tokens=trace.context_tokens,
        retrieval_ms=trace.retrieval_ms,
        generation_ms=trace.generation_ms,
        generation_model=trace.generation_model,
    )


@router.get("", response_model=TraceList)
def list_traces(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> TraceList:
    traces = session.scalars(
        select(QueryTrace).order_by(QueryTrace.created_at.desc()).limit(limit)
    ).all()

    total = session.scalar(select(func.count()).select_from(QueryTrace)) or 0
    refused = (
        session.scalar(
            select(func.count()).select_from(QueryTrace).where(QueryTrace.refused.is_(True))
        )
        or 0
    )
    invalid = (
        session.scalar(
            select(func.count())
            .select_from(QueryTrace)
            .where(func.cardinality(QueryTrace.invalid_citations) > 0)
        )
        or 0
    )

    # Percentiles over answered queries only: a refusal takes no generation
    # time, and including those zeros would flatter the latency numbers.
    percentiles = session.execute(
        select(
            func.percentile_cont(0.5).within_group(QueryTrace.generation_ms),
            func.percentile_cont(0.95).within_group(QueryTrace.generation_ms),
        ).where(QueryTrace.refused.is_(False))
    ).first()

    return TraceList(
        stats=TraceStats(
            total=total,
            refused=refused,
            with_invalid_citations=invalid,
            p50_generation_ms=int(percentiles[0]) if percentiles and percentiles[0] else None,
            p95_generation_ms=int(percentiles[1]) if percentiles and percentiles[1] else None,
        ),
        traces=[_to_out(t) for t in traces],
    )
