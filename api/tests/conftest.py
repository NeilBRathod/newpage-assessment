"""Shared test fixtures.

The suite is offline by construction: both the database session and the settings
are injected through FastAPI's dependency overrides, so no test reaches Postgres
or Ollama. That is the point of the provider seam — tests stay fast and
deterministic, and nothing depends on ambient environment variables.
"""

import os

import pytest
import sqlalchemy
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

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


# --- integration fixtures -------------------------------------------------
#
# Everything above runs offline. The fixtures below need a real Postgres with
# pgvector, because the schema uses vector, ARRAY and generated tsvector columns
# that no in-memory database implements. They skip cleanly when there is no
# database, so `make test` stays useful on a laptop with nothing running, and CI
# provides the service so they actually execute.


def _integration_database_url() -> str | None:
    return os.environ.get("MEETINGIQ_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def engine():
    url = _integration_database_url()
    if not url:
        pytest.skip("set MEETINGIQ_TEST_DATABASE_URL to run integration tests")

    engine = sqlalchemy.create_engine(url, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text("SELECT 1"))
    except sqlalchemy.exc.SQLAlchemyError as exc:
        pytest.skip(f"integration database unreachable: {exc.__class__.__name__}")

    from meetingiq import models  # noqa: F401  (registers tables on Base)
    from meetingiq.db import Base

    with engine.begin() as connection:
        connection.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(engine):
    """A session rolled back after each test, so tests cannot leak into each other."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
