"""Shared test fixtures.

The suite is offline by construction: both the database session and the settings
are injected through FastAPI's dependency overrides, so no test reaches Postgres
or Ollama. That is the point of the provider seam — tests stay fast and
deterministic, and nothing depends on ambient environment variables.
"""

import pytest
from fastapi.testclient import TestClient

from meetingiq.config import Provider, Settings, get_settings
from meetingiq.db import get_session
from meetingiq.main import create_app


class FakeSession:
    """Minimal stand-in for a SQLAlchemy session in health checks."""

    def __init__(self, *, healthy: bool = True, pgvector_version: str | None = "0.8.0"):
        self._healthy = healthy
        self._pgvector_version = pgvector_version

    def execute(self, statement):
        if not self._healthy:
            raise ConnectionError("database is down")
        return _FakeResult(self._pgvector_version, str(statement))


class _FakeResult:
    def __init__(self, pgvector_version: str | None, statement: str):
        self._pgvector_version = pgvector_version
        self._statement = statement

    def scalar(self):
        if "pg_extension" in self._statement:
            return self._pgvector_version
        return 1


@pytest.fixture
def make_client():
    """Builds a TestClient with injectable fake database and settings."""

    def _make(
        session: FakeSession | None = None,
        settings: Settings | None = None,
    ) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_session] = lambda: session or FakeSession()
        app.dependency_overrides[get_settings] = lambda: (
            settings or Settings(provider=Provider.FAKE)
        )
        return TestClient(app)

    return _make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()
