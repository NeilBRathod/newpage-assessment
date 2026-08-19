"""Provider interfaces.

Two narrow Protocols rather than a framework. The whole surface the application
needs from a model backend is "turn text into vectors" and "turn a prompt into
text", and stating that explicitly means the test suite can satisfy it in thirty
lines and run with no network at all.

Embedding is asymmetric on purpose. EmbeddingGemma is trained with different
prefixes for queries and documents, and using one prefix for both degrades
retrieval with no error and no obvious symptom — so the distinction is pushed
into the type rather than left to a caller to remember.
"""

from collections.abc import Iterator, Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable


class EmbeddingKind(StrEnum):
    DOCUMENT = "document"
    QUERY = "query"


class ProviderError(RuntimeError):
    """A model backend failed or returned something unusable."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...

    def embed(
        self,
        texts: Sequence[str],
        *,
        kind: EmbeddingKind,
        titles: Sequence[str] | None = None,
    ) -> list[list[float]]:
        """Embed `texts`. `titles` is used for document-side prefixes only."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str: ...

    def stream(self, *, system: str, prompt: str, max_tokens: int = 1024) -> Iterator[str]: ...
