"""The ask endpoint.

Streaming is the default because generation on a local 12B model takes tens of
seconds. Without it the user stares at nothing; with it, excerpts appear
immediately and text arrives as it is produced.
"""

import json
import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from meetingiq.config import Settings, get_settings
from meetingiq.db import get_session
from meetingiq.llm.base import EmbeddingProvider, LLMProvider
from meetingiq.llm.registry import get_embedding_provider, get_llm_provider
from meetingiq.rag.answer import AnswerResult, answer_question, stream_answer
from meetingiq.schemas import AskRequest, AskResponse, ExcerptOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def embedding_provider(settings: Annotated[Settings, Depends(get_settings)]) -> EmbeddingProvider:
    return get_embedding_provider(settings)


def llm_provider(settings: Annotated[Settings, Depends(get_settings)]) -> LLMProvider:
    return get_llm_provider(settings)


def _to_response(result: AnswerResult) -> AskResponse:
    return AskResponse(
        question=result.question,
        answer=result.answer,
        refused=result.refused,
        refusal_reason=str(result.refusal_reason) if result.refusal_reason else None,
        citations=result.citations,
        excerpts=[
            ExcerptOut.from_chunk(index, chunk)
            for index, chunk in enumerate(result.excerpts, start=1)
        ],
        filters_applied=result.filters_applied,
        top_similarity=result.top_similarity,
        retrieval_ms=result.retrieval_ms,
        generation_ms=result.generation_ms,
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    embedder: Annotated[EmbeddingProvider, Depends(embedding_provider)],
    llm: Annotated[LLMProvider, Depends(llm_provider)],
):
    """Answer a question. Streams Server-Sent Events unless `stream` is false."""
    if not request.stream:
        result = answer_question(
            session,
            question=request.question,
            settings=settings,
            embedder=embedder,
            llm=llm,
            meeting_ids=request.meeting_ids,
        )
        return _to_response(result)

    def events() -> Iterator[str]:
        try:
            for event, payload in stream_answer(
                session,
                question=request.question,
                settings=settings,
                embedder=embedder,
                llm=llm,
                meeting_ids=request.meeting_ids,
            ):
                match event:
                    case "excerpts":
                        yield _sse(
                            "excerpts",
                            [
                                ExcerptOut.from_chunk(index, chunk).model_dump()
                                for index, chunk in enumerate(payload, start=1)
                            ],
                        )
                    case "token":
                        yield _sse("token", {"text": payload})
                    case "refusal":
                        yield _sse("refusal", payload)
                    case "done":
                        yield _sse("done", _to_response(payload).model_dump())
        except Exception as exc:
            # The response has already started, so an exception here cannot
            # become a 500 — the client would just see the stream stop. Send a
            # terminal error event instead.
            logger.exception("streaming answer failed")
            yield _sse("error", {"message": f"{exc.__class__.__name__}: {exc}"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
