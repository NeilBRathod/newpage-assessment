"""Trace recording tests.

Two claims worth pinning: a trace captures enough to explain a bad answer after
the fact, and failing to record one never breaks the answer itself.
"""

from unittest.mock import Mock

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from meetingiq.config import Provider, Settings
from meetingiq.models import QueryTrace
from meetingiq.observability import traces
from meetingiq.rag.answer import AnswerResult
from meetingiq.rag.guardrails import CitationAudit, RefusalReason
from tests.test_guardrails import chunk


def result(**overrides) -> AnswerResult:
    defaults = {
        "question": "Did we reverse the ledger decision?",
        "answer": "Yes, on the 14th [1].",
        "refused": False,
        "refusal_reason": None,
        "excerpts": [chunk(similarity=0.45, chunk_id="c1")],
        "citations": [1],
        "filters_applied": "none",
        "top_similarity": 0.45,
        "retrieval_ms": 18,
        "generation_ms": 42_000,
        "audit": CitationAudit(cited=[1], invalid=[], is_grounded=True, looks_like_refusal=False),
    }
    return AnswerResult(**{**defaults, **overrides})


def test_records_a_query(db_session):
    traces.record(db_session, result(), Settings(provider=Provider.FAKE))

    trace = db_session.scalar(select(QueryTrace))
    assert trace.question.startswith("Did we reverse")
    assert trace.citations == [1]
    assert trace.generation_ms == 42_000


def test_records_why_a_chunk_ranked_where_it_did(db_session):
    """Without this a bad answer cannot be diagnosed after the fact."""
    traces.record(db_session, result(), Settings(provider=Provider.FAKE))

    [row] = db_session.scalar(select(QueryTrace)).retrieved
    assert row["chunk_id"] == "c1"
    assert row["similarity"] == 0.45
    assert row["vector_rank"] == 1
    assert row["cited"] is True


def test_records_refusals_too(db_session):
    """A refusal is a query outcome; excluding them would hide the guardrail."""
    traces.record(
        db_session,
        result(
            refused=True,
            refusal_reason=RefusalReason.BELOW_RELEVANCE_FLOOR,
            excerpts=[],
            citations=[],
            generation_ms=0,
            audit=None,
        ),
        Settings(provider=Provider.FAKE),
    )

    trace = db_session.scalar(select(QueryTrace))
    assert trace.refused is True
    assert trace.refusal_reason == "below_relevance_floor"
    assert trace.retrieved == []


def test_records_fabricated_citations(db_session):
    traces.record(
        db_session,
        result(
            audit=CitationAudit(
                cited=[1, 9], invalid=[9], is_grounded=True, looks_like_refusal=False
            )
        ),
        Settings(provider=Provider.FAKE),
    )

    assert db_session.scalar(select(QueryTrace)).invalid_citations == [9]


def test_records_the_model_that_produced_the_answer(db_session):
    """Comparing yesterday's traces to today's is meaningless without it."""
    traces.record(
        db_session,
        result(),
        Settings(provider=Provider.FAKE, generation_model="gemma4:12b"),
    )

    assert db_session.scalar(select(QueryTrace)).generation_model == "gemma4:12b"


def test_a_failed_trace_write_never_breaks_the_answer():
    """The record of what happened must not become the reason it didn't."""
    session = Mock()
    session.commit.side_effect = SQLAlchemyError("disk full")

    traces.record(session, result(), Settings(provider=Provider.FAKE))

    session.rollback.assert_called_once()
