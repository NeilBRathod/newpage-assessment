"""Deterministic in-process providers for tests.

The fake embedder is a hashing vectoriser rather than random noise: each token
lands in a bucket and the vector is L2-normalised, so texts sharing vocabulary
end up with genuinely higher cosine similarity. That makes retrieval tests
meaningful — a query about "reconciliation" really does rank the reconciliation
chunk first — without a model, a network call, or a GPU.

It is not a semantic model. It cannot match synonyms, and it is not meant to.
Retrieval *quality* is measured against the real model in the eval harness; what
these fakes verify is that the plumbing is correct.
"""

import hashlib
import math
import re
from collections.abc import Iterator, Sequence

from meetingiq.llm.base import EmbeddingKind

_TOKEN = re.compile(r"[a-z0-9']+")


class FakeEmbeddingProvider:
    def __init__(self, dimensions: int = 768):
        self._dimensions = dimensions
        self.calls: list[tuple[EmbeddingKind, int]] = []

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.sha1(token.encode()).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            # Sign from a second byte so unrelated tokens can cancel rather than
            # only ever accumulating.
            vector[bucket] += 1.0 if digest[4] % 2 else -1.0

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            # An empty or punctuation-only string still needs a unit vector.
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]

    def embed(
        self,
        texts: Sequence[str],
        *,
        kind: EmbeddingKind,
        titles: Sequence[str] | None = None,
    ) -> list[list[float]]:
        self.calls.append((kind, len(texts)))
        return [self._vector(text) for text in texts]


class FakeLLMProvider:
    """Returns a canned answer and records what it was asked."""

    def __init__(self, response: str = "A fake answer."):
        self.response = response
        self.prompts: list[tuple[str, str]] = []
        self.schemas: list[dict | None] = []

    def generate(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 1024,
        schema: dict | None = None,
    ) -> str:
        self.prompts.append((system, prompt))
        self.schemas.append(schema)
        return self.response

    def stream(self, *, system: str, prompt: str, max_tokens: int = 1024) -> Iterator[str]:
        self.prompts.append((system, prompt))
        yield from self.response.split(" ")
