"""Answer orchestration: retrieve, assemble, generate, verify.

The order matters. Filters narrow before ranking, the relevance floor runs
before the generator is called at all, and citations are audited after. Each
stage records what it did so a bad answer can be explained rather than guessed
at.
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from meetingiq.config import Settings
from meetingiq.llm.base import EmbeddingKind, EmbeddingProvider, LLMProvider
from meetingiq.rag.guardrails import (
    CitationAudit,
    RefusalReason,
    audit_citations,
    check_relevance,
    strip_invalid_citations,
)
from meetingiq.rag.prompts import REFUSAL_MESSAGE, SYSTEM_PROMPT, build_context, build_prompt
from meetingiq.retrieval.filters import RetrievalFilters, extract_filters
from meetingiq.retrieval.hybrid import RetrievedChunk, hybrid_search

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AnswerResult:
    question: str
    answer: str
    refused: bool
    refusal_reason: RefusalReason | None
    excerpts: list[RetrievedChunk] = field(default_factory=list)
    citations: list[int] = field(default_factory=list)
    filters_applied: str = "none"
    top_similarity: float | None = None
    retrieval_ms: int = 0
    generation_ms: int = 0
    audit: CitationAudit | None = None


@dataclass(slots=True)
class _Prepared:
    """Everything decided before generation, shared by the sync and streaming paths."""

    excerpts: list[RetrievedChunk]
    prompt: str
    filters: RetrievalFilters
    top_similarity: float | None
    retrieval_ms: int
    refusal_reason: RefusalReason | None


def _prepare(
    session: Session,
    *,
    question: str,
    settings: Settings,
    embedder: EmbeddingProvider,
    meeting_ids: list[str] | None = None,
) -> _Prepared:
    started = time.perf_counter()

    filters = extract_filters(session, question)
    if meeting_ids:
        # An explicit UI selection is a stronger signal than anything inferred
        # from the wording, so it replaces rather than adds to it.
        filters = RetrievalFilters(
            meeting_ids=meeting_ids,
            speakers=filters.speakers,
            date_from=filters.date_from,
            date_to=filters.date_to,
        )

    [query_vector] = embedder.embed([question], kind=EmbeddingKind.QUERY)

    chunks = hybrid_search(
        session,
        query=question,
        embedding=query_vector,
        filters=filters,
        candidates=settings.retrieval_candidates,
        top_k=settings.retrieval_top_k,
        rrf_k=settings.rrf_k,
    )

    # A filter inferred from wording can be wrong — a question may name someone
    # who is discussed rather than speaking. Rather than refuse, fall back to
    # the whole corpus when filtering leaves nothing at all.
    if not chunks and not filters.is_empty and not meeting_ids:
        logger.info("filters matched nothing; retrying unfiltered", extra={"question": question})
        filters = RetrievalFilters()
        chunks = hybrid_search(
            session,
            query=question,
            embedding=query_vector,
            filters=filters,
            candidates=settings.retrieval_candidates,
            top_k=settings.retrieval_top_k,
            rrf_k=settings.rrf_k,
        )

    verdict = check_relevance(chunks, minimum_similarity=settings.min_retrieval_score)
    retrieval_ms = int((time.perf_counter() - started) * 1000)

    if not verdict.should_answer:
        logger.info(
            "refusing before generation",
            extra={"reason": str(verdict.reason), "top_similarity": verdict.top_similarity},
        )
        return _Prepared([], "", filters, verdict.top_similarity, retrieval_ms, verdict.reason)

    context, included = build_context(chunks, max_tokens=settings.max_context_tokens)
    return _Prepared(
        excerpts=included,
        prompt=build_prompt(question, context),
        filters=filters,
        top_similarity=verdict.top_similarity,
        retrieval_ms=retrieval_ms,
        refusal_reason=None,
    )


def _finalise(
    question: str, raw_answer: str, prepared: _Prepared, generation_ms: int
) -> AnswerResult:
    audit = audit_citations(raw_answer, excerpt_count=len(prepared.excerpts))
    if audit.has_invalid_citations:
        logger.warning(
            "answer cited excerpts that were never supplied",
            extra={"invalid": audit.invalid, "supplied": len(prepared.excerpts)},
        )
    answer = strip_invalid_citations(raw_answer, excerpt_count=len(prepared.excerpts))

    return AnswerResult(
        question=question,
        answer=answer,
        refused=False,
        refusal_reason=None,
        excerpts=prepared.excerpts,
        citations=[index for index in audit.cited if index not in audit.invalid],
        filters_applied=prepared.filters.describe(),
        top_similarity=prepared.top_similarity,
        retrieval_ms=prepared.retrieval_ms,
        generation_ms=generation_ms,
        audit=audit,
    )


def _refusal(question: str, prepared: _Prepared) -> AnswerResult:
    return AnswerResult(
        question=question,
        answer=REFUSAL_MESSAGE,
        refused=True,
        refusal_reason=prepared.refusal_reason,
        filters_applied=prepared.filters.describe(),
        top_similarity=prepared.top_similarity,
        retrieval_ms=prepared.retrieval_ms,
    )


def answer_question(
    session: Session,
    *,
    question: str,
    settings: Settings,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    meeting_ids: list[str] | None = None,
) -> AnswerResult:
    prepared = _prepare(
        session, question=question, settings=settings, embedder=embedder, meeting_ids=meeting_ids
    )
    if prepared.refusal_reason is not None:
        return _refusal(question, prepared)

    started = time.perf_counter()
    raw = llm.generate(
        system=SYSTEM_PROMPT, prompt=prepared.prompt, max_tokens=settings.max_answer_tokens
    )
    generation_ms = int((time.perf_counter() - started) * 1000)

    return _finalise(question, raw, prepared, generation_ms)


def stream_answer(
    session: Session,
    *,
    question: str,
    settings: Settings,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    meeting_ids: list[str] | None = None,
) -> Iterator[tuple[str, object]]:
    """Yield (event, payload) pairs for SSE.

    Excerpts are emitted before the first token so the UI can render its
    evidence panel while generation is still running — on a local model that is
    the difference between a blank screen for twenty seconds and something to
    read immediately.

    Invalid citations cannot be stripped mid-stream without buffering the whole
    answer and losing the point of streaming, so the audit is emitted in the
    final event and the client reconciles.
    """
    prepared = _prepare(
        session, question=question, settings=settings, embedder=embedder, meeting_ids=meeting_ids
    )
    if prepared.refusal_reason is not None:
        result = _refusal(question, prepared)
        yield "refusal", {"answer": result.answer, "reason": str(result.refusal_reason)}
        yield "done", result
        return

    yield "excerpts", prepared.excerpts

    started = time.perf_counter()
    parts: list[str] = []
    for token in llm.stream(
        system=SYSTEM_PROMPT, prompt=prepared.prompt, max_tokens=settings.max_answer_tokens
    ):
        parts.append(token)
        yield "token", token
    generation_ms = int((time.perf_counter() - started) * 1000)

    yield "done", _finalise(question, "".join(parts), prepared, generation_ms)
