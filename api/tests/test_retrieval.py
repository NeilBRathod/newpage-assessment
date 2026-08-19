"""Retrieval tests.

RRF is a pure function and gets tested directly. Hybrid search and filter
extraction need real Postgres — full-text search and vector distance are the
things under test, so faking them would test nothing.
"""

import pytest
from sqlalchemy import select

from meetingiq.config import Provider, Settings
from meetingiq.ingest.pipeline import ingest_transcript
from meetingiq.llm.base import EmbeddingKind
from meetingiq.llm.fake import FakeEmbeddingProvider
from meetingiq.models import Meeting
from meetingiq.retrieval.filters import RetrievalFilters, extract_filters
from meetingiq.retrieval.hybrid import hybrid_search, reciprocal_rank_fusion

# --- RRF (pure) -----------------------------------------------------------


def test_rrf_rewards_agreement_between_retrievers():
    """A document both retrievers like should beat one only a single list ranks."""
    vector = ["a", "b", "c"]
    text = ["c", "b", "z"]

    scores = reciprocal_rank_fusion([vector, text])

    assert scores["b"] > scores["a"]
    assert scores["b"] > scores["z"]


def test_rrf_uses_rank_not_score():
    """Position is all that matters, which is why no normalisation is needed."""
    scores = reciprocal_rank_fusion([["x", "y"]], k=60)

    assert scores["x"] == pytest.approx(1 / 61)
    assert scores["y"] == pytest.approx(1 / 62)


def test_rrf_k_damps_the_advantage_of_first_place():
    small_k = reciprocal_rank_fusion([["x", "y"]], k=1)
    large_k = reciprocal_rank_fusion([["x", "y"]], k=1000)

    assert small_k["x"] / small_k["y"] > large_k["x"] / large_k["y"]


def test_rrf_of_nothing_is_empty():
    assert reciprocal_rank_fusion([]) == {}
    assert reciprocal_rank_fusion([[], []]) == {}


def test_rrf_sums_across_lists_for_a_document_in_both():
    scores = reciprocal_rank_fusion([["a"], ["a"]], k=60)

    assert scores["a"] == pytest.approx(2 / 61)


# --- integration ----------------------------------------------------------

TRANSCRIPT_A = """\
# Meeting: Architecture Review
# Date: 2026-04-14
# Participants: Dana Osei, Priya Raman

[00:00:05] Dana Osei: I benchmarked the ledger and the p99 latency is four seconds.
[00:00:40] Priya Raman: Then we reverse the decision and build a separate settlement service.
[00:01:20] Dana Osei: Reconciliation between the two will need PAY-1042 on day one.
"""

TRANSCRIPT_B = """\
# Meeting: Budget Review
# Date: 2026-05-26
# Participants: Ben Cutler, Priya Raman

[00:00:05] Ben Cutler: Infrastructure spend is fourteen thousand a month and rising.
[00:00:50] Priya Raman: Staging is sized like production for no reason anyone remembers.
"""


@pytest.fixture
def corpus(db_session):
    settings = Settings(provider=Provider.FAKE)
    embedder = FakeEmbeddingProvider(settings.embedding_dimensions)
    for raw, name in [(TRANSCRIPT_A, "arch.txt"), (TRANSCRIPT_B, "budget.txt")]:
        ingest_transcript(
            db_session, raw_text=raw, filename=name, settings=settings, embedder=embedder
        )
    return embedder


def search(session, embedder, question, **kwargs):
    [vector] = embedder.embed([question], kind=EmbeddingKind.QUERY)
    return hybrid_search(session, query=question, embedding=vector, **kwargs)


def test_finds_an_exact_ticket_id_that_dense_retrieval_would_blur(corpus, db_session):
    """The case hybrid search exists for: identifiers embed almost identically."""
    results = search(db_session, corpus, "PAY-1042")

    assert results
    assert "PAY-1042" in results[0].text
    # It came from the full-text side, which is the point.
    assert results[0].text_rank is not None


def test_results_carry_the_provenance_of_their_ranking(corpus, db_session):
    """A trace has to be able to say why something ranked where it did."""
    results = search(db_session, corpus, "reconciliation and the ledger")

    assert results[0].rrf_score > 0
    assert results[0].vector_rank or results[0].text_rank


def test_top_k_limits_results(corpus, db_session):
    results = search(db_session, corpus, "the ledger", top_k=1)

    assert len(results) == 1


def test_meeting_filter_narrows_before_ranking(corpus, db_session):
    """Filtering after retrieval could leave nothing at all."""
    budget_id = str(db_session.scalar(select(Meeting.id).where(Meeting.title == "Budget Review")))

    results = search(
        db_session, corpus, "the ledger", filters=RetrievalFilters(meeting_ids=[budget_id])
    )

    assert all(r.meeting_id == budget_id for r in results)


def test_speaker_filter_restricts_to_chunks_that_speaker_is_in(corpus, db_session):
    results = search(db_session, corpus, "spend", filters=RetrievalFilters(speakers=["Ben Cutler"]))

    assert results
    assert all("Ben Cutler" in r.speakers for r in results)


def test_search_over_an_empty_corpus_returns_nothing(db_session):
    embedder = FakeEmbeddingProvider(768)

    assert search(db_session, embedder, "anything at all") == []


# --- filter extraction ----------------------------------------------------


def test_extracts_a_speaker_named_in_the_question(corpus, db_session):
    filters = extract_filters(db_session, "What did Ben Cutler say about spend?")

    assert filters.speakers == ["Ben Cutler"]


def test_matches_a_first_name_when_it_is_unambiguous(corpus, db_session):
    filters = extract_filters(db_session, "What did Dana benchmark?")

    assert filters.speakers == ["Dana Osei"]


def test_does_not_guess_when_a_first_name_is_ambiguous(db_session):
    """Silently picking one of two Danas would exclude the other's turns."""
    filters = extract_filters(
        db_session, "What did Dana say?", known_speakers=["Dana Osei", "Dana Whitfield"]
    )

    assert filters.speakers == []


def test_a_question_naming_nobody_produces_no_filters(corpus, db_session):
    filters = extract_filters(db_session, "What was decided about latency?")

    assert filters.is_empty


def test_does_not_match_a_name_inside_another_word(db_session):
    filters = extract_filters(
        db_session, "What about bendable pipes?", known_speakers=["Ben Cutler"]
    )

    assert filters.speakers == []
