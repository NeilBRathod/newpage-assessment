"""Writing query traces.

Kept out of the answer pipeline's happy path on purpose: a trace is a record of
what happened, and failing to record it must never turn a good answer into an
error. Every write is best-effort and logged if it fails.
"""

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from meetingiq.config import Settings
from meetingiq.ingest.chunker import estimate_tokens
from meetingiq.models import QueryTrace
from meetingiq.rag.answer import AnswerResult

logger = logging.getLogger(__name__)


def _retrieved_rows(result: AnswerResult) -> list[dict]:
    return [
        {
            "index": index,
            "chunk_id": chunk.chunk_id,
            "meeting": chunk.meeting_title,
            "vector_rank": chunk.vector_rank,
            "text_rank": chunk.text_rank,
            "similarity": chunk.vector_similarity,
            "rrf": round(chunk.rrf_score, 6),
            "cited": index in result.citations,
        }
        for index, chunk in enumerate(result.excerpts, start=1)
    ]


def record(session: Session, result: AnswerResult, settings: Settings) -> None:
    """Persist one answered question. Never raises."""
    try:
        session.add(
            QueryTrace(
                question=result.question,
                answer=result.answer,
                refused=result.refused,
                refusal_reason=str(result.refusal_reason) if result.refusal_reason else None,
                retrieved=_retrieved_rows(result),
                citations=result.citations,
                invalid_citations=result.audit.invalid if result.audit else [],
                filters_applied=result.filters_applied[:500],
                top_similarity=result.top_similarity,
                excerpt_count=len(result.excerpts),
                context_tokens=sum(estimate_tokens(c.text) for c in result.excerpts),
                retrieval_ms=result.retrieval_ms,
                generation_ms=result.generation_ms,
                provider=str(settings.provider),
                generation_model=settings.generation_model,
            )
        )
        session.commit()
    except SQLAlchemyError:
        # A trace is a record of what happened; losing it must not turn a good
        # answer into an error for the user.
        session.rollback()
        logger.exception("failed to record query trace")
