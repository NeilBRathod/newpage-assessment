"""Provider selection.

One place that maps the configured provider name onto concrete implementations,
so nothing else in the codebase needs to know which backend is in use.
"""

from meetingiq.config import Provider, Settings
from meetingiq.llm.base import EmbeddingProvider, LLMProvider
from meetingiq.llm.fake import FakeEmbeddingProvider, FakeLLMProvider
from meetingiq.llm.ollama import OllamaEmbeddingProvider, OllamaLLMProvider
from meetingiq.llm.openai import OpenAIEmbeddingProvider, OpenAILLMProvider


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    match settings.provider:
        case Provider.OLLAMA:
            return OllamaEmbeddingProvider(settings)
        case Provider.FAKE:
            return FakeEmbeddingProvider(settings.embedding_dimensions)
        case Provider.OPENAI:
            return OpenAIEmbeddingProvider(settings)


def get_llm_provider(settings: Settings) -> LLMProvider:
    match settings.provider:
        case Provider.OLLAMA:
            return OllamaLLMProvider(settings)
        case Provider.FAKE:
            return FakeLLMProvider()
        case Provider.OPENAI:
            return OpenAILLMProvider(settings)
