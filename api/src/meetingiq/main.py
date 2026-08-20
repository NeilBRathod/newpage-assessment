"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from meetingiq import __version__
from meetingiq.config import get_settings
from meetingiq.observability.logging import configure_logging
from meetingiq.routers import briefs, chat, health, meetings

logger = logging.getLogger(__name__)

# Configured at import rather than in the lifespan hook: uvicorn emits its own
# startup lines before lifespan runs, and those would otherwise escape as
# unstructured text into an otherwise JSON-only stream.
configure_logging(get_settings().log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "starting",
        extra={
            "version": __version__,
            "provider": settings.provider,
            "generation_model": settings.generation_model,
            "embedding_model": settings.embedding_model,
            "num_ctx": settings.num_ctx,
        },
    )
    yield
    logger.info("shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Meeting Intelligence System",
        description="RAG over meeting transcripts, with speaker- and timestamp-level citations.",
        version=__version__,
        lifespan=lifespan,
    )

    # The web app is served from a different origin in development.
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(meetings.router)
    app.include_router(chat.router)
    app.include_router(briefs.router)
    return app


app = create_app()
