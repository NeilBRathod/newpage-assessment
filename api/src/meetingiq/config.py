"""Application settings.

Every value is overridable by environment variable with the ``MEETINGIQ_``
prefix, so the same image runs locally, in CI, and (eventually) on a hyperscaler
without code changes.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Provider(StrEnum):
    """Which model backend to use.

    ``fake`` is what the test suite runs against — it keeps the suite offline and
    deterministic, which is the main reason the provider seam exists at all.
    """

    OLLAMA = "ollama"
    OPENAI = "openai"
    FAKE = "fake"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEETINGIQ_",
        env_file=".env",
        extra="ignore",
    )

    # ---- Database ----
    database_url: str = "postgresql+psycopg://meetingiq:meetingiq@localhost:5433/meetingiq"

    # ---- Provider selection ----
    provider: Provider = Provider.OLLAMA

    # ---- Ollama ----
    # Ollama runs natively on the host for GPU access. Only the containerised
    # path (`make docker-up`) overrides this to host.docker.internal.
    ollama_base_url: str = "http://localhost:11434"
    generation_model: str = "gemma4:12b"
    embedding_model: str = "embeddinggemma:300m"
    embedding_dimensions: int = 768

    # Ollama defaults num_ctx to 2048 no matter what the model actually supports.
    # Left unset, retrieved context is silently truncated and the model answers
    # from almost nothing — the single easiest way to get a quietly broken RAG
    # system. Sent explicitly on every generation call.
    num_ctx: int = 32768

    # ---- Optional cloud fallback ----
    openai_api_key: str | None = None
    openai_generation_model: str = "gpt-5-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # ---- Retrieval / generation knobs ----
    # Defaults chosen in the plan; see docs/PLAN.md for the reasoning.
    chunk_target_tokens: int = 350
    chunk_max_tokens: int = 500
    retrieval_candidates: int = 20
    retrieval_top_k: int = 8
    rrf_k: int = 60
    # Below this fused score the question is refused without calling the LLM.
    min_retrieval_score: float = 0.02
    # Hard ceiling on assembled context, well inside num_ctx to leave room for
    # the system prompt, the question, and the answer.
    max_context_tokens: int = 12000

    # ---- App ----
    # Origins allowed to call the API. Keep in step with the web dev server's
    # port (VITE_PORT); an allowlist is used rather than "*" so that tightening
    # this for a real deployment is a config change, not a code change.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    log_level: str = "INFO"
    request_timeout_seconds: float = Field(default=180.0)


@lru_cache
def get_settings() -> Settings:
    """Cached so settings are read once per process."""
    return Settings()
