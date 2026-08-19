"""Health endpoint.

Deliberately more than a 200/OK. A RAG system has three ways to be quietly
broken — no database, no model server, or a model server that is up but missing
the models it is asked for — and all three produce plausible-looking failures
much later in the pipeline. This surfaces them at the front door.
"""

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from meetingiq.config import Provider, Settings, get_settings
from meetingiq.db import get_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class Check(BaseModel):
    ok: bool
    detail: str


class HealthResponse(BaseModel):
    status: str
    version: str
    checks: dict[str, Check]


def _check_database(session: Session) -> Check:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        return Check(ok=False, detail=f"unreachable: {exc.__class__.__name__}")

    installed = session.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if installed is None:
        return Check(ok=False, detail="reachable, but the pgvector extension is not installed")
    return Check(ok=True, detail=f"reachable, pgvector {installed}")


def _fetch_ollama_models(settings: Settings) -> list[str]:
    response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5.0)
    response.raise_for_status()
    return [model["name"] for model in response.json().get("models", [])]


def _check_models(settings: Settings) -> tuple[Check, Check]:
    """Returns (ollama reachability, model presence)."""
    try:
        available = _fetch_ollama_models(settings)
    except Exception as exc:
        unreachable = Check(ok=False, detail=f"unreachable at {settings.ollama_base_url}: {exc}")
        return unreachable, Check(ok=False, detail="cannot check — Ollama unreachable")

    reachable = Check(ok=True, detail=f"reachable at {settings.ollama_base_url}")

    # Ollama reports tags as "name:tag"; a bare "name" means ":latest".
    normalised = {name if ":" in name else f"{name}:latest" for name in available}
    wanted = {
        "generation": settings.generation_model,
        "embedding": settings.embedding_model,
    }
    missing = {
        role: model
        for role, model in wanted.items()
        if (model if ":" in model else f"{model}:latest") not in normalised
    }
    if missing:
        pulls = "; ".join(f"ollama pull {model}" for model in missing.values())
        return reachable, Check(ok=False, detail=f"missing {missing} — run: {pulls}")

    return reachable, Check(
        ok=True, detail=f"{wanted['generation']}, {wanted['embedding']} present"
    )


def _check_context_window(settings: Settings) -> Check:
    """Guard against the Ollama num_ctx default.

    Ollama serves every model with a 2048-token context unless told otherwise,
    which silently truncates retrieved context. This does not stop the app, but
    a num_ctx that cannot hold the configured context budget guarantees
    ungrounded answers, so it is reported as a failure rather than a warning.
    """
    if settings.num_ctx < settings.max_context_tokens:
        return Check(
            ok=False,
            detail=(
                f"num_ctx={settings.num_ctx} is below max_context_tokens="
                f"{settings.max_context_tokens}; retrieved context would be truncated"
            ),
        )
    return Check(ok=True, detail=f"num_ctx={settings.num_ctx}")


@router.get("/health", response_model=HealthResponse)
def health(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    checks = {"database": _check_database(session)}

    if settings.provider is Provider.OLLAMA:
        checks["ollama"], checks["models"] = _check_models(settings)
        checks["context_window"] = _check_context_window(settings)
    else:
        checks["provider"] = Check(ok=True, detail=f"using {settings.provider} provider")

    healthy = all(check.ok for check in checks.values())
    if not healthy:
        response.status_code = 503
        logger.warning(
            "health check degraded",
            extra={"failed": [name for name, c in checks.items() if not c.ok]},
        )

    from meetingiq import __version__

    return HealthResponse(
        status="ok" if healthy else "degraded",
        version=__version__,
        checks=checks,
    )
