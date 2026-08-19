"""API tests for /ask and /meetings.

Run against real Postgres with fake model providers: the retrieval is real (it
is what these endpoints are for) while generation is deterministic, so the tests
assert on plumbing rather than on what a language model felt like saying.
"""

import json

import pytest
from fastapi.testclient import TestClient

from meetingiq.config import Provider, Settings
from meetingiq.db import get_session
from meetingiq.ingest.pipeline import ingest_transcript
from meetingiq.llm.fake import FakeEmbeddingProvider, FakeLLMProvider
from meetingiq.llm.registry import get_embedding_provider
from meetingiq.main import create_app
from meetingiq.routers.chat import embedding_provider, llm_provider

TRANSCRIPT = """\
# Meeting: Architecture Review
# Date: 2026-04-14
# Participants: Dana Osei, Priya Raman

[00:00:05] Dana Osei: I benchmarked the ledger and the p99 latency is four seconds.
[00:00:40] Priya Raman: Then we reverse the decision and build a separate settlement service.
[00:01:20] Dana Osei: Reconciliation will need PAY-1042 on day one.
"""


@pytest.fixture
def settings() -> Settings:
    # A floor of zero keeps these tests about plumbing; the floor itself is
    # covered directly in test_guardrails.
    return Settings(provider=Provider.FAKE, min_retrieval_score=0.0)


@pytest.fixture
def app_client(db_session, settings):
    def _build(answer: str = "The decision was reversed [1]."):
        ingest_transcript(
            db_session,
            raw_text=TRANSCRIPT,
            filename="arch.txt",
            settings=settings,
            embedder=get_embedding_provider(settings),
        )
        app = create_app()
        app.dependency_overrides[get_session] = lambda: db_session
        from meetingiq.config import get_settings

        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[embedding_provider] = lambda: FakeEmbeddingProvider(768)
        app.dependency_overrides[llm_provider] = lambda: FakeLLMProvider(answer)
        return TestClient(app)

    return _build


def sse_events(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append((event, json.loads(data)))
    return events


def test_answers_a_question_with_excerpts_and_citations(app_client):
    client = app_client()

    response = client.post("/ask", json={"question": "What was decided?", "stream": False})

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is False
    assert body["citations"] == [1]
    assert body["excerpts"]
    assert body["excerpts"][0]["index"] == 1


def test_excerpts_carry_what_the_evidence_panel_needs(app_client):
    client = app_client()

    body = client.post("/ask", json={"question": "the ledger", "stream": False}).json()

    excerpt = body["excerpts"][0]
    assert excerpt["meeting_title"] == "Architecture Review"
    assert excerpt["utterance_seqs"]
    assert excerpt["start_s"] >= 0
    # Retrieval provenance, so ranking is inspectable from the UI.
    assert "rrf_score" in excerpt


def test_a_fabricated_citation_never_reaches_the_client(app_client):
    """The model was shown a handful of excerpts; [99] cannot be one of them."""
    client = app_client(answer="As agreed [99].")

    body = client.post("/ask", json={"question": "the ledger", "stream": False}).json()

    assert "[99]" not in body["answer"]
    assert 99 not in body["citations"]


def test_refuses_when_the_corpus_is_empty(db_session, settings):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    from meetingiq.config import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[embedding_provider] = lambda: FakeEmbeddingProvider(768)
    app.dependency_overrides[llm_provider] = lambda: FakeLLMProvider()
    client = TestClient(app)

    body = client.post("/ask", json={"question": "anything", "stream": False}).json()

    assert body["refused"] is True
    assert body["refusal_reason"] == "no_results"


def test_refusal_does_not_call_the_generator(db_session, settings):
    """Refusing early is the point: it saves a slow local generation."""
    llm = FakeLLMProvider()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    from meetingiq.config import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[embedding_provider] = lambda: FakeEmbeddingProvider(768)
    app.dependency_overrides[llm_provider] = lambda: llm
    client = TestClient(app)

    client.post("/ask", json={"question": "anything", "stream": False})

    assert llm.prompts == []


def test_streaming_sends_excerpts_before_any_token(app_client):
    """So the UI can render evidence while a slow local model is still going."""
    client = app_client()

    with client.stream("POST", "/ask", json={"question": "the ledger"}) as response:
        events = sse_events("".join(response.iter_text()))

    names = [name for name, _ in events]
    assert names[0] == "excerpts"
    assert "token" in names
    assert names[-1] == "done"


def test_streaming_final_event_carries_the_audited_answer(app_client):
    client = app_client(answer="Reversed [1] and also [99].")

    with client.stream("POST", "/ask", json={"question": "the ledger"}) as response:
        events = sse_events("".join(response.iter_text()))

    _, done = events[-1]
    assert "[99]" not in done["answer"]
    assert done["citations"] == [1]


def test_rejects_an_empty_question(app_client):
    client = app_client()

    assert client.post("/ask", json={"question": "", "stream": False}).status_code == 422


# --- meetings -------------------------------------------------------------


def test_lists_meetings(app_client):
    client = app_client()

    body = client.get("/meetings").json()

    assert len(body) == 1
    assert body[0]["title"] == "Architecture Review"
    assert body[0]["participants"] == ["Dana Osei", "Priya Raman"]


def test_returns_a_full_transcript_for_the_evidence_panel(app_client):
    client = app_client()
    meeting_id = client.get("/meetings").json()[0]["id"]

    body = client.get(f"/meetings/{meeting_id}/transcript").json()

    assert [u["seq"] for u in body["utterances"]] == [0, 1, 2]
    assert body["utterances"][0]["speaker"] == "Dana Osei"


def test_unknown_meeting_is_a_404(app_client):
    client = app_client()

    response = client.get("/meetings/00000000-0000-0000-0000-000000000000/transcript")

    assert response.status_code == 404


def test_corpus_stats(app_client):
    client = app_client()

    body = client.get("/meetings/stats/corpus").json()

    assert body == {"meetings": 1, "utterances": 3, "speakers": 2}
