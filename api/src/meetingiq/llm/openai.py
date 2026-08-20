"""OpenAI-backed providers.

The optional cloud path. Local inference is the default — for meeting
transcripts, keeping data on the machine is a product argument as much as a cost
one — but two things make a hosted adapter worth shipping rather than merely
describing. Local generation is slow enough (tens of seconds per answer on a
laptop) to make iterating on prompts and running the eval suite painful, and a
reviewer without Ollama and 8GB of models can still run the system.

Called over plain HTTP rather than through the OpenAI SDK: the surface used here
is two endpoints, and httpx is already a dependency for talking to Ollama.
"""

import json
import logging
from collections.abc import Iterator, Sequence

import httpx

from meetingiq.config import Settings
from meetingiq.llm.base import EmbeddingKind, ProviderError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.openai.com/v1"


class OpenAIEmbeddingProvider:
    """OpenAI embeddings, truncated to match the schema.

    text-embedding-3-* are natively 1536- and 3072-dimensional, but support a
    `dimensions` parameter that truncates using Matryoshka representation. That
    is what keeps this adapter drop-in against a `vector(768)` column sized for
    EmbeddingGemma.

    Switching providers still means re-embedding the corpus. Vectors from
    different models are not comparable, so mixing them in one index produces
    retrieval that is quietly wrong rather than obviously broken.
    """

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if not settings.openai_api_key:
            raise ProviderError("MEETINGIQ_PROVIDER=openai but OPENAI_API_KEY is not set")
        self._settings = settings
        self._client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )

    @property
    def dimensions(self) -> int:
        return self._settings.embedding_dimensions

    def embed(
        self,
        texts: Sequence[str],
        *,
        kind: EmbeddingKind,
        titles: Sequence[str] | None = None,
    ) -> list[list[float]]:
        # OpenAI's embedding models are symmetric — unlike EmbeddingGemma they
        # take no task prefix, so `kind` and `titles` are accepted to satisfy
        # the Protocol and deliberately unused.
        del kind, titles
        if not texts:
            return []

        try:
            response = self._client.post(
                f"{_BASE_URL}/embeddings",
                json={
                    "model": self._settings.openai_embedding_model,
                    "input": list(texts),
                    "dimensions": self.dimensions,
                },
            )
            response.raise_for_status()
            data = response.json()["data"]
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            raise ProviderError(f"embedding request failed: {exc}") from exc

        # The API documents that results may not come back in request order.
        ordered = sorted(data, key=lambda item: item["index"])
        return [item["embedding"] for item in ordered]


class OpenAILLMProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if not settings.openai_api_key:
            raise ProviderError("MEETINGIQ_PROVIDER=openai but OPENAI_API_KEY is not set")
        self._settings = settings
        self._client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )

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
            "model": self._settings.openai_generation_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": max_tokens,
            "stream": stream,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction",
                    # Strict mode requires every property to be required and
                    # additionalProperties false; the schema is passed through
                    # as authored, so keep it that way when adding fields.
                    "strict": False,
                    "schema": schema,
                },
            }
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
                f"{_BASE_URL}/chat/completions",
                json=self._payload(system, prompt, max_tokens, stream=False, schema=schema),
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ProviderError(f"generation request failed: {exc}") from exc

    def stream(self, *, system: str, prompt: str, max_tokens: int = 1024) -> Iterator[str]:
        try:
            with self._client.stream(
                "POST",
                f"{_BASE_URL}/chat/completions",
                json=self._payload(system, prompt, max_tokens, stream=True),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    body = line.removeprefix("data: ").strip()
                    if body == "[DONE]":
                        return
                    delta = json.loads(body)["choices"][0].get("delta", {})
                    if content := delta.get("content"):
                        yield content
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ProviderError(f"streaming generation failed: {exc}") from exc
