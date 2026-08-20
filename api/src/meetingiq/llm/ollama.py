"""Ollama-backed providers.

Runs against Ollama on the host so the model can use the GPU. See docs/PLAN.md
for why that is not in a container.
"""

import json
import logging
from collections.abc import Iterator, Sequence

import httpx

from meetingiq.config import Settings
from meetingiq.llm.base import EmbeddingKind, ProviderError

logger = logging.getLogger(__name__)

# EmbeddingGemma's documented prompt templates. Queries and documents take
# different prefixes; using the same one for both silently costs retrieval
# quality. The model card notes a real title beats the "none" placeholder, and
# meeting transcripts have one.
_QUERY_PREFIX = "task: search result | query: "
_DOCUMENT_TEMPLATE = "title: {title} | text: {text}"


class OllamaEmbeddingProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.request_timeout_seconds)

    @property
    def dimensions(self) -> int:
        return self._settings.embedding_dimensions

    def _apply_prefix(
        self, texts: Sequence[str], kind: EmbeddingKind, titles: Sequence[str] | None
    ) -> list[str]:
        if kind is EmbeddingKind.QUERY:
            return [f"{_QUERY_PREFIX}{text}" for text in texts]
        # Chunk.embedding_input() already applies the document template when a
        # title is known; only bare text needs wrapping here.
        if titles is None:
            return [_DOCUMENT_TEMPLATE.format(title="none", text=text) for text in texts]
        if len(titles) != len(texts):
            raise ValueError("titles must be the same length as texts")
        return [
            _DOCUMENT_TEMPLATE.format(title=title or "none", text=text)
            for title, text in zip(titles, texts, strict=True)
        ]

    def embed(
        self,
        texts: Sequence[str],
        *,
        kind: EmbeddingKind,
        titles: Sequence[str] | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []

        payload = {
            "model": self._settings.embedding_model,
            "input": self._apply_prefix(texts, kind, titles),
            # Ollama evicts idle models after five minutes by default, and the
            # 8GB generator readily pushes this one out. Reloading it costs the
            # user ~15s on the next question, for the sake of 0.7GB of RAM, so
            # it is pinned for longer.
            "keep_alive": self._settings.embedding_keep_alive,
        }
        try:
            response = self._client.post(
                f"{self._settings.ollama_base_url}/api/embed", json=payload
            )
            response.raise_for_status()
            embeddings = response.json()["embeddings"]
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise ProviderError(f"embedding request failed: {exc}") from exc

        if len(embeddings) != len(texts):
            raise ProviderError(f"expected {len(texts)} embeddings, got {len(embeddings)}")
        for vector in embeddings:
            if len(vector) != self.dimensions:
                raise ProviderError(
                    f"model returned {len(vector)}-dimensional vectors but the schema "
                    f"expects {self.dimensions}; the embedding column and "
                    f"MEETINGIQ_EMBEDDING_DIMENSIONS must match the model"
                )
        return embeddings


class OllamaLLMProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.request_timeout_seconds)

    def _payload(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        *,
        stream: bool,
        schema: dict | None = None,
    ) -> dict:
        payload = {
            "model": self._settings.generation_model,
            "system": system,
            "prompt": prompt,
            "stream": stream,
            # Gemma 4 thinks before answering unless told not to.
            "think": self._settings.enable_thinking,
            "options": {
                # Ollama defaults this to 2048 whatever the model supports.
                # Omitting it silently truncates retrieved context.
                "num_ctx": self._settings.num_ctx,
                "num_predict": max_tokens,
                # Grounded extraction, not creative writing.
                "temperature": 0.2,
            },
        }
        if schema is not None:
            payload["format"] = schema
        return payload

    def generate(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 1024,
        schema: dict | None = None,
    ) -> str:
        try:
            response = self._client.post(
                f"{self._settings.ollama_base_url}/api/generate",
                json=self._payload(system, prompt, max_tokens, stream=False, schema=schema),
            )
            response.raise_for_status()
            return response.json()["response"]
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise ProviderError(f"generation request failed: {exc}") from exc

    def stream(self, *, system: str, prompt: str, max_tokens: int = 1024) -> Iterator[str]:
        try:
            with self._client.stream(
                "POST",
                f"{self._settings.ollama_base_url}/api/generate",
                json=self._payload(system, prompt, max_tokens, stream=True),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if chunk := event.get("response"):
                        yield chunk
                    if event.get("done"):
                        return
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ProviderError(f"streaming generation failed: {exc}") from exc
