"""Provider tests.

The asymmetric-prefix behaviour is the part worth guarding: using a query prefix
on a document (or none at all) costs retrieval quality silently, with no error
and no obvious symptom.
"""

import httpx
import pytest

from meetingiq.config import Provider, Settings
from meetingiq.llm.base import EmbeddingKind, ProviderError
from meetingiq.llm.fake import FakeEmbeddingProvider
from meetingiq.llm.ollama import OllamaEmbeddingProvider, OllamaLLMProvider
from meetingiq.llm.registry import get_embedding_provider, get_llm_provider


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def embedding_handler(captured: list[dict], dimensions: int = 768):
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(
            200, json={"embeddings": [[0.1] * dimensions for _ in payload["input"]]}
        )

    return handler


def test_query_and_document_get_different_prefixes():
    captured: list[dict] = []
    provider = OllamaEmbeddingProvider(Settings(), mock_client(embedding_handler(captured)))

    provider.embed(["what did Dana say"], kind=EmbeddingKind.QUERY)
    provider.embed(["Dana Osei: I ran the benchmark"], kind=EmbeddingKind.DOCUMENT)

    assert captured[0]["input"][0].startswith("task: search result | query: ")
    assert captured[1]["input"][0].startswith("title: none | text: ")


def test_document_prefix_uses_a_real_title_when_given():
    """The model card notes a real title outperforms the 'none' placeholder."""
    captured: list[dict] = []
    provider = OllamaEmbeddingProvider(Settings(), mock_client(embedding_handler(captured)))

    provider.embed(["some turns"], kind=EmbeddingKind.DOCUMENT, titles=["Relay Kickoff"])

    assert captured[0]["input"][0] == "title: Relay Kickoff | text: some turns"


def test_rejects_mismatched_titles_length():
    provider = OllamaEmbeddingProvider(Settings(), mock_client(embedding_handler([])))

    with pytest.raises(ValueError, match="same length"):
        provider.embed(["a", "b"], kind=EmbeddingKind.DOCUMENT, titles=["only one"])


def test_embedding_of_nothing_makes_no_request():
    def handler(request):  # pragma: no cover - must never be called
        raise AssertionError("should not have issued a request")

    provider = OllamaEmbeddingProvider(Settings(), mock_client(handler))

    assert provider.embed([], kind=EmbeddingKind.QUERY) == []


def test_wrong_dimensions_fail_loudly():
    """A model/schema mismatch would otherwise surface as an opaque DB error."""
    provider = OllamaEmbeddingProvider(
        Settings(embedding_dimensions=768), mock_client(embedding_handler([], dimensions=384))
    )

    with pytest.raises(ProviderError, match="384-dimensional"):
        provider.embed(["text"], kind=EmbeddingKind.QUERY)


def test_transport_failure_becomes_a_provider_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    provider = OllamaEmbeddingProvider(Settings(), mock_client(handler))

    with pytest.raises(ProviderError, match="embedding request failed"):
        provider.embed(["text"], kind=EmbeddingKind.QUERY)


def test_generation_always_sends_num_ctx():
    """Omitting it means Ollama uses 2048 and silently truncates context."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"response": "ok"})

    provider = OllamaLLMProvider(Settings(num_ctx=32768), mock_client(handler))
    provider.generate(system="s", prompt="p")

    assert captured[0]["options"]["num_ctx"] == 32768


def test_streaming_yields_chunks_and_stops_at_done():
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            '{"response": "Hello", "done": false}\n'
            '{"response": " world", "done": false}\n'
            '{"response": "", "done": true}\n'
        )
        return httpx.Response(200, content=body)

    provider = OllamaLLMProvider(Settings(), mock_client(handler))

    assert list(provider.stream(system="s", prompt="p")) == ["Hello", " world"]


# --- fake provider --------------------------------------------------------


def test_fake_embeddings_are_deterministic():
    provider = FakeEmbeddingProvider()

    first = provider.embed(["reconciliation drift"], kind=EmbeddingKind.QUERY)
    second = provider.embed(["reconciliation drift"], kind=EmbeddingKind.QUERY)

    assert first == second


def test_fake_embeddings_rank_shared_vocabulary_higher():
    """Weak but not meaningless, so retrieval plumbing can be tested offline."""
    provider = FakeEmbeddingProvider()

    query, related, unrelated = provider.embed(
        [
            "reconciliation between the ledger and settlement",
            "we need reconciliation between settlement and the ledger",
            "the pricing is thirty basis points per transaction",
        ],
        kind=EmbeddingKind.QUERY,
    )

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert dot(query, related) > dot(query, unrelated)


def test_fake_embeddings_are_unit_length_even_for_empty_text():
    provider = FakeEmbeddingProvider(dimensions=8)

    [vector] = provider.embed([""], kind=EmbeddingKind.QUERY)

    assert abs(sum(v * v for v in vector) - 1.0) < 1e-9


def test_registry_selects_by_configured_provider():
    settings = Settings(provider=Provider.FAKE)

    assert isinstance(get_embedding_provider(settings), FakeEmbeddingProvider)
    assert get_llm_provider(settings).generate(system="", prompt="") == "A fake answer."


def test_openai_provider_requires_a_key():
    settings = Settings(provider=Provider.OPENAI, openai_api_key=None)

    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        get_embedding_provider(settings)
