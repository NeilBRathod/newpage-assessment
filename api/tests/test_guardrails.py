"""Guardrail tests.

These encode the two claims the guardrails actually make: a citation pointing
outside the supplied excerpts is fabricated and must not reach the user, and a
question with no connection to the corpus should not reach the generator.

Note what is deliberately *not* claimed. Citation validation cannot show an
answer is grounded, only that its references exist. A model can still cite [2]
for something [2] does not support.
"""

import pytest

from meetingiq.rag.guardrails import (
    RefusalReason,
    audit_citations,
    check_relevance,
    strip_invalid_citations,
)
from meetingiq.retrieval.hybrid import RetrievedChunk


def chunk(similarity: float | None = 0.5, chunk_id: str = "c1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        meeting_id="m1",
        meeting_title="Kickoff",
        meeting_date="2026-04-07",
        seq=0,
        text="Dana Osei: I benchmarked it.",
        context_header="Meeting: Kickoff",
        speakers=["Dana Osei"],
        start_s=0.0,
        end_s=10.0,
        utterance_seqs=[0],
        vector_rank=1,
        text_rank=None,
        vector_similarity=similarity,
        rrf_score=0.016,
    )


# --- relevance floor ------------------------------------------------------


def test_no_results_is_refused():
    verdict = check_relevance([], minimum_similarity=0.2)

    assert not verdict.should_answer
    assert verdict.reason is RefusalReason.NO_RESULTS


def test_a_question_unrelated_to_the_corpus_is_refused_before_generation():
    """Measured: "what is the capital of France?" scores 0.069 against this corpus."""
    verdict = check_relevance([chunk(similarity=0.069)], minimum_similarity=0.2)

    assert not verdict.should_answer
    assert verdict.reason is RefusalReason.BELOW_RELEVANCE_FLOOR


def test_a_borderline_question_is_allowed_through():
    """The floor is set low on purpose; near-misses are the generator's job.

    Measured on the seed corpus, top-1 similarity does not separate answerable
    from unanswerable questions — the legitimate "When did we decide to move
    GA?" scores 0.295, below the unanswerable "August board meeting" at 0.386.
    A floor high enough to catch the second would reject the first.
    """
    verdict = check_relevance([chunk(similarity=0.295)], minimum_similarity=0.2)

    assert verdict.should_answer


def test_text_only_matches_are_not_refused():
    """A full-text hit with no vector rank is a real lexical match, e.g. a ticket id."""
    verdict = check_relevance([chunk(similarity=None)], minimum_similarity=0.9)

    assert verdict.should_answer


def test_the_best_match_decides_not_the_worst():
    verdict = check_relevance(
        [chunk(similarity=0.05, chunk_id="a"), chunk(similarity=0.6, chunk_id="b")],
        minimum_similarity=0.2,
    )

    assert verdict.should_answer
    assert verdict.top_similarity == 0.6


# --- citation auditing ----------------------------------------------------


def test_accepts_citations_within_the_supplied_range():
    audit = audit_citations("The decision was reversed [2].", excerpt_count=8)

    assert audit.cited == [2]
    assert audit.invalid == []
    assert audit.is_grounded


def test_flags_a_citation_outside_the_supplied_range():
    """The model was given 1..3 and nothing else, so [9] is fabricated."""
    audit = audit_citations("As discussed [9].", excerpt_count=3)

    assert audit.invalid == [9]
    assert audit.has_invalid_citations


@pytest.mark.parametrize("text", ["Reversed [1, 4].", "Reversed [1,4].", "Reversed [1 , 4]."])
def test_parses_grouped_citations(text):
    """Models group references interchangeably; matching only "[2]" under-counts."""
    audit = audit_citations(text, excerpt_count=8)

    assert audit.cited == [1, 4]


def test_an_uncited_assertion_is_not_treated_as_grounded():
    audit = audit_citations("They decided to build a separate service.", excerpt_count=3)

    assert not audit.is_grounded


def test_an_honest_refusal_counts_as_grounded_despite_having_no_citations():
    audit = audit_citations(
        "The transcripts don't cover the Frankfurt data centre.", excerpt_count=3
    )

    assert audit.looks_like_refusal
    assert audit.is_grounded


# --- stripping ------------------------------------------------------------


def test_removes_a_citation_that_points_nowhere():
    cleaned = strip_invalid_citations("Decided [9]. Reversed [2].", excerpt_count=3)

    assert "[9]" not in cleaned
    assert "[2]" in cleaned


def test_keeps_the_valid_half_of_a_grouped_citation():
    """Dropping the whole group would discard a legitimate reference."""
    cleaned = strip_invalid_citations("Reversed [3, 42].", excerpt_count=8)

    assert cleaned == "Reversed [3]."


def test_does_not_leave_a_gap_before_punctuation():
    cleaned = strip_invalid_citations("Decided [9].", excerpt_count=3)

    assert cleaned == "Decided."


def test_leaves_an_answer_with_no_citations_alone():
    assert strip_invalid_citations("No citations here.", excerpt_count=3) == "No citations here."
