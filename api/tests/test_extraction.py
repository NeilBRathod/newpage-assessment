"""Extraction tests.

The quote-matching logic is the interesting part and is tested directly: it is
what turns "the model might be inventing things" from a worry into something
countable, so it needs to be neither too strict (flagging real quotes over a
smart apostrophe) nor too loose (accepting anything).
"""

import json

import pytest
from sqlalchemy import select

from meetingiq.config import Provider, Settings
from meetingiq.extraction.brief import (
    SCHEMA,
    GroundingStats,
    canonical_owner,
    extract_brief,
    match_quote,
)
from meetingiq.ingest.parser import Utterance as ParsedUtterance
from meetingiq.ingest.pipeline import ingest_transcript
from meetingiq.llm.fake import FakeEmbeddingProvider, FakeLLMProvider
from meetingiq.models import ActionItem, Decision, Meeting

TRANSCRIPT = """\
# Meeting: Architecture Review
# Date: 2026-04-14
# Participants: Dana Osei, Priya Raman

[00:00:05] Dana Osei: Median was eight hundred and forty milliseconds. That's fine.
[00:00:40] Priya Raman: Then we're reversing last week's decision.
[00:01:20] Dana Osei: I'll have the design doc by the twenty-first.
"""

EXTRACTION = json.dumps(
    {
        "summary": "The team reversed the ledger decision after a benchmark.",
        "decisions": [
            {
                "text": "Build a separate settlement service instead of extending the ledger.",
                "quote": "Then we're reversing last week's decision.",
            }
        ],
        "action_items": [
            {
                "owner": "Dana Osei",
                "description": "Write the design doc.",
                "due": "the twenty-first",
                "quote": "I'll have the design doc by the twenty-first.",
            }
        ],
    }
)


def utterances(*texts: str) -> list[ParsedUtterance]:
    return [
        ParsedUtterance(seq=i, speaker="Dana Osei", start_s=float(i), end_s=float(i + 1), text=t)
        for i, t in enumerate(texts)
    ]


# --- quote matching (pure) ------------------------------------------------


def test_matches_an_exact_quote():
    turns = utterances("The p99 was four point two seconds.")

    assert match_quote("The p99 was four point two seconds.", turns) is turns[0]


def test_matches_despite_smart_punctuation():
    """Models normalise typography; that is not evidence of fabrication."""
    turns = utterances("It\u2019s the tail \u2014 p99 was four point two seconds.")

    assert match_quote("It's the tail - p99 was four point two seconds.", turns) is turns[0]


def test_matches_a_quote_truncated_from_a_longer_turn():
    turns = utterances("Median was eight hundred and forty milliseconds. That's fine.")

    assert match_quote("Median was eight hundred and forty milliseconds", turns) is turns[0]


def test_matches_when_the_model_padded_a_short_turn():
    turns = utterances("The fourteenth.")

    assert match_quote("Dana said: the fourteenth.", turns) is turns[0]


def test_rejects_a_quote_that_is_not_in_the_transcript():
    """The point of the mechanism: an invented quote must not match."""
    turns = utterances("Median was eight hundred and forty milliseconds.")

    assert match_quote("We agreed to open a Frankfurt data centre.", turns) is None


def test_rejects_a_near_miss_paraphrase():
    # Real case from the seed corpus: the model wrote "provisionly" for
    # "provisionally", i.e. reconstructed the quote instead of copying it.
    turns = utterances("So let's provisionally go with option one, extend the ledger.")

    assert match_quote("So let's provisionly go with option one, extend the ledger.", turns) is None


def test_rejects_a_quote_too_short_to_be_evidence():
    """ "Yes" appears in every meeting and proves nothing."""
    turns = utterances("Yes, that's right and here is a much longer sentence.")

    assert match_quote("Yes", turns) is None


def test_no_utterances_means_no_match():
    assert match_quote("anything at all here", []) is None


# --- grounding stats ------------------------------------------------------


def test_grounding_rate_is_none_when_nothing_was_measured():
    """Reporting 100% for a cached read would flatter work that never happened."""
    assert GroundingStats(total=0, grounded=0).rate is None


def test_grounding_rate_is_a_fraction():
    assert GroundingStats(total=4, grounded=3).rate == 0.75


# --- schema ---------------------------------------------------------------


def test_due_is_required_so_the_model_cannot_skip_it():
    """Left optional, it was omitted on every single extraction."""
    assert "due" in SCHEMA["properties"]["action_items"]["items"]["required"]


def test_every_extracted_item_must_carry_a_quote():
    assert "quote" in SCHEMA["properties"]["decisions"]["items"]["required"]
    assert "quote" in SCHEMA["properties"]["action_items"]["items"]["required"]


# --- integration ----------------------------------------------------------


@pytest.fixture
def meeting(db_session):
    settings = Settings(provider=Provider.FAKE)
    result = ingest_transcript(
        db_session,
        raw_text=TRANSCRIPT,
        filename="arch.txt",
        settings=settings,
        embedder=FakeEmbeddingProvider(settings.embedding_dimensions),
    )
    return result.meeting_id


def test_extraction_stores_decisions_and_actions(db_session, meeting):
    llm = FakeLLMProvider(EXTRACTION)

    result = extract_brief(
        db_session, meeting_id=meeting, settings=Settings(provider=Provider.FAKE), llm=llm
    )

    assert result.decision_count == 1
    assert result.action_count == 1
    assert db_session.scalar(select(Decision)).text.startswith("Build a separate")
    action = db_session.scalar(select(ActionItem))
    assert action.owner == "Dana Osei"
    assert action.due == "the twenty-first"


def test_extraction_is_constrained_by_a_schema(db_session, meeting):
    """Not "please return JSON" — the decoder is restricted."""
    llm = FakeLLMProvider(EXTRACTION)

    extract_brief(
        db_session, meeting_id=meeting, settings=Settings(provider=Provider.FAKE), llm=llm
    )

    assert llm.schemas[0] == SCHEMA


def test_items_are_linked_back_to_the_turn_they_came_from(db_session, meeting):
    llm = FakeLLMProvider(EXTRACTION)

    result = extract_brief(
        db_session, meeting_id=meeting, settings=Settings(provider=Provider.FAKE), llm=llm
    )

    assert result.grounding.rate == 1.0
    action = db_session.scalar(select(ActionItem))
    assert action.utterance_seq == 2
    assert action.speaker == "Dana Osei"


def test_a_fabricated_quote_is_stored_but_flagged(db_session, meeting):
    """It is kept, not dropped — an unverifiable item is worth showing as such."""
    fabricated = json.dumps(
        {
            "summary": "s",
            "decisions": [
                {"text": "Open a Frankfurt data centre.", "quote": "We agreed on Frankfurt."}
            ],
            "action_items": [],
        }
    )

    result = extract_brief(
        db_session,
        meeting_id=meeting,
        settings=Settings(provider=Provider.FAKE),
        llm=FakeLLMProvider(fabricated),
    )

    assert result.grounding.rate == 0.0
    assert result.grounding.ungrounded_quotes
    decision = db_session.scalar(select(Decision))
    assert decision.utterance_seq is None


def test_a_second_call_reads_the_cache_without_calling_the_model(db_session, meeting):
    settings = Settings(provider=Provider.FAKE)
    llm = FakeLLMProvider(EXTRACTION)
    extract_brief(db_session, meeting_id=meeting, settings=settings, llm=llm)

    result = extract_brief(db_session, meeting_id=meeting, settings=settings, llm=llm)

    assert result.cached
    assert len(llm.prompts) == 1


def test_force_replaces_rather_than_accumulates(db_session, meeting):
    settings = Settings(provider=Provider.FAKE)
    llm = FakeLLMProvider(EXTRACTION)
    extract_brief(db_session, meeting_id=meeting, settings=settings, llm=llm)

    extract_brief(db_session, meeting_id=meeting, settings=settings, llm=llm, force=True)

    assert len(db_session.scalars(select(Decision)).all()) == 1
    assert len(db_session.scalars(select(ActionItem)).all()) == 1


def test_extraction_marks_the_meeting_as_extracted(db_session, meeting):
    extract_brief(
        db_session,
        meeting_id=meeting,
        settings=Settings(provider=Provider.FAKE),
        llm=FakeLLMProvider(EXTRACTION),
    )

    assert db_session.get(Meeting, meeting).extracted_at is not None


def test_unknown_meeting_raises(db_session):
    with pytest.raises(LookupError):
        extract_brief(
            db_session,
            meeting_id="00000000-0000-0000-0000-000000000000",
            settings=Settings(provider=Provider.FAKE),
            llm=FakeLLMProvider(EXTRACTION),
        )


# --- owner canonicalisation -----------------------------------------------


def test_resolves_a_first_name_to_the_speaker_who_used_it():
    """The model writes "Dana Osei" in one meeting and "Dana" in the next."""
    speakers = ["Dana Osei", "Priya Raman"]

    assert canonical_owner("Dana", speakers) == "Dana Osei"


def test_owner_matching_ignores_case_and_spacing():
    assert canonical_owner("  dana   osei ", ["Dana Osei"]) == "Dana Osei"


def test_leaves_an_ambiguous_first_name_alone():
    """Guessing between two Danas would assign work to the wrong person."""
    assert canonical_owner("Dana", ["Dana Osei", "Dana Whitfield"]) == "Dana"


def test_keeps_an_owner_who_was_not_in_the_meeting():
    """People are given work in meetings they did not attend."""
    assert canonical_owner("Nadia", ["Dana Osei"]) == "Nadia"


def test_canonicalises_owners_when_storing(db_session, meeting):
    """Otherwise one person appears twice on the action board."""
    payload = json.dumps(
        {
            "summary": "s",
            "decisions": [],
            "action_items": [
                {
                    "owner": "Dana",
                    "description": "Write the design doc.",
                    "due": "",
                    "quote": "I'll have the design doc by the twenty-first.",
                }
            ],
        }
    )

    extract_brief(
        db_session,
        meeting_id=meeting,
        settings=Settings(provider=Provider.FAKE),
        llm=FakeLLMProvider(payload),
    )

    assert db_session.scalar(select(ActionItem)).owner == "Dana Osei"
