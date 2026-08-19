"""Tests for the health endpoint.

Health is worth testing properly because it is the thing that tells you *why*
the system is broken. A health check that reports green when a model is missing
is worse than no health check.
"""

import pytest

from meetingiq.config import Provider, Settings
from meetingiq.routers.health import _check_context_window, _check_models
from tests.conftest import FakeSession


def test_health_ok_with_fake_provider(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["ok"] is True
    assert "pgvector 0.8.0" in body["checks"]["database"]["detail"]


def test_health_reports_503_when_database_is_down(make_client):
    client = make_client(FakeSession(healthy=False))

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["database"]["ok"] is False


def test_health_fails_when_pgvector_is_missing(make_client):
    """A reachable Postgres without the extension is the subtler failure."""
    client = make_client(FakeSession(pgvector_version=None))

    response = client.get("/health")

    assert response.status_code == 503
    assert "pgvector extension is not installed" in response.json()["checks"]["database"]["detail"]


@pytest.mark.parametrize(
    ("available", "expected_ok"),
    [
        (["gemma4:12b", "embeddinggemma:300m"], True),
        (["gemma4:12b"], False),
        ([], False),
        # Ollama reports an implicit ":latest"; both spellings must match.
        (["gemma4:12b", "embeddinggemma:300m", "mistral"], True),
    ],
)
def test_model_presence_check(monkeypatch, available, expected_ok):
    settings = Settings(provider=Provider.OLLAMA)
    monkeypatch.setattr(
        "meetingiq.routers.health._fetch_ollama_models", lambda _settings: available
    )

    reachable, models = _check_models(settings)

    assert reachable.ok is True
    assert models.ok is expected_ok


def test_model_check_suggests_the_pull_command(monkeypatch):
    settings = Settings(provider=Provider.OLLAMA)
    monkeypatch.setattr("meetingiq.routers.health._fetch_ollama_models", lambda _s: [])

    _, models = _check_models(settings)

    assert "ollama pull gemma4:12b" in models.detail


def test_unreachable_ollama_is_reported_without_raising(monkeypatch):
    def boom(_settings):
        raise ConnectionError("connection refused")

    settings = Settings(provider=Provider.OLLAMA)
    monkeypatch.setattr("meetingiq.routers.health._fetch_ollama_models", boom)

    reachable, models = _check_models(settings)

    assert reachable.ok is False
    assert models.ok is False


def test_context_window_check_catches_the_ollama_num_ctx_default():
    """The 2048 default silently truncates context; it must fail loudly."""
    settings = Settings(num_ctx=2048, max_context_tokens=12000)

    check = _check_context_window(settings)

    assert check.ok is False
    assert "truncated" in check.detail


def test_context_window_check_passes_when_configured():
    settings = Settings(num_ctx=32768, max_context_tokens=12000)

    assert _check_context_window(settings).ok is True
