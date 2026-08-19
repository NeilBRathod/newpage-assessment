"""Chunker tests.

These assert invariants rather than exact output, because the exact chunk
boundaries are a tuning decision that should be free to change. What must not
change is that turns stay whole, chunks stay inside the budget, and consecutive
chunks overlap.
"""

from datetime import date
from itertools import pairwise

import pytest

from meetingiq.ingest.chunker import chunk_transcript, estimate_tokens, format_timestamp
from meetingiq.ingest.parser import ParsedTranscript, TranscriptFormat, Utterance


def make_transcript(utterances: list[Utterance], **kwargs) -> ParsedTranscript:
    return ParsedTranscript(
        title=kwargs.get("title", "Weekly Sync"),
        meeting_date=kwargs.get("meeting_date", date(2026, 3, 4)),
        duration_s=kwargs.get("duration_s", 600.0),
        participants=kwargs.get("participants", []),
        source_format=TranscriptFormat.BRACKETED,
        utterances=utterances,
    )


def turns(count: int, words: int = 40, speakers: tuple[str, ...] = ("Ada", "Alan")):
    return [
        Utterance(
            seq=i,
            speaker=speakers[i % len(speakers)],
            start_s=float(i * 10),
            end_s=float(i * 10 + 9),
            text=" ".join(f"word{i}x{w}" for w in range(words)),
        )
        for i in range(count)
    ]


def test_groups_turns_into_chunks():
    chunks = chunk_transcript(make_transcript(turns(30)), target_tokens=350, max_tokens=500)

    assert len(chunks) > 1
    assert [c.seq for c in chunks] == list(range(len(chunks)))


def test_never_splits_a_turn_across_chunks():
    """The core invariant: a chunk contains whole turns or none of them."""
    utterances = turns(30)
    chunks = chunk_transcript(make_transcript(utterances), target_tokens=350, max_tokens=500)

    for chunk in chunks:
        for line in chunk.text.split("\n"):
            speaker, _, body = line.partition(": ")
            assert any(u.speaker == speaker and u.text == body for u in utterances), (
                f"chunk contains a partial turn: {line[:60]!r}"
            )


def test_every_turn_appears_somewhere():
    """Chunking must not lose content."""
    utterances = turns(30)
    chunks = chunk_transcript(make_transcript(utterances))

    covered = {seq for chunk in chunks for seq in chunk.utterance_seqs}
    assert covered == {u.seq for u in utterances}


def test_chunks_respect_the_token_budget():
    chunks = chunk_transcript(make_transcript(turns(40)), target_tokens=200, max_tokens=300)

    # A chunk may exceed the target by its final turn, but never the ceiling.
    assert all(c.token_estimate <= 300 for c in chunks)


def test_consecutive_chunks_overlap_by_one_turn():
    """Pronouns do not respect chunk boundaries."""
    chunks = chunk_transcript(make_transcript(turns(30)), target_tokens=250, overlap_turns=1)

    for previous, following in pairwise(chunks):
        assert previous.utterance_seqs[-1] == following.utterance_seqs[0]


def test_overlap_can_be_disabled():
    chunks = chunk_transcript(make_transcript(turns(30)), target_tokens=250, overlap_turns=0)

    for previous, following in pairwise(chunks):
        assert previous.utterance_seqs[-1] < following.utterance_seqs[0]


def test_a_single_over_long_turn_is_split_on_sentence_boundaries():
    """Keeping it whole would make a chunk too coarse to retrieve precisely."""
    monologue = Utterance(
        seq=0,
        speaker="Ada",
        start_s=0.0,
        end_s=600.0,
        text=" ".join(f"This is sentence number {i} of a very long speech." for i in range(120)),
    )
    chunks = chunk_transcript(make_transcript([monologue]), target_tokens=200, max_tokens=300)

    assert len(chunks) > 1
    assert all(c.token_estimate <= 300 for c in chunks)
    # Every fragment still resolves back to the turn actually spoken.
    assert all(c.utterance_seqs == [0] for c in chunks)
    assert all(c.speakers == ["Ada"] for c in chunks)


def test_split_turn_does_not_cut_mid_sentence():
    monologue = Utterance(
        seq=0,
        speaker="Ada",
        start_s=0.0,
        end_s=60.0,
        text=" ".join(f"Sentence {i} ends here." for i in range(60)),
    )
    chunks = chunk_transcript(make_transcript([monologue]), target_tokens=150, max_tokens=200)

    for chunk in chunks:
        body = chunk.text.removeprefix("Ada: ").strip()
        assert body.endswith("."), f"chunk ends mid-sentence: {body[-40:]!r}"


def test_chunking_terminates_when_one_turn_fills_a_whole_chunk():
    """A regression guard: naive overlap can stall the loop here."""
    utterances = [
        Utterance(
            seq=i,
            speaker="Ada",
            start_s=float(i),
            end_s=float(i + 1),
            text=" ".join(f"w{i}x{w}" for w in range(80)),
        )
        for i in range(6)
    ]
    chunks = chunk_transcript(make_transcript(utterances), target_tokens=120, max_tokens=400)

    assert len(chunks) == 6


def test_context_header_carries_meeting_date_speakers_and_time_range():
    """This header is what lets the vector capture who and when, not just what."""
    chunks = chunk_transcript(make_transcript(turns(6)), target_tokens=1000, max_tokens=1000)

    header = chunks[0].context_header
    assert "Meeting: Weekly Sync" in header
    assert "Date: 2026-03-04" in header
    assert "Ada" in header and "Alan" in header
    assert "00:00:00-" in header


def test_embedding_input_uses_the_document_template():
    """EmbeddingGemma is asymmetric; documents take title/text, not a query prefix."""
    chunks = chunk_transcript(make_transcript(turns(4)), target_tokens=1000, max_tokens=1000)

    rendered = chunks[0].embedding_input("Weekly Sync")
    assert rendered.startswith("title: Weekly Sync | text: ")
    assert "task: search result" not in rendered


def test_chunk_text_keeps_speaker_names_inline():
    """So full-text search can match on who said something."""
    chunks = chunk_transcript(make_transcript(turns(4)), target_tokens=1000, max_tokens=1000)

    assert chunks[0].text.startswith("Ada: ")


def test_chunk_time_range_spans_its_turns():
    chunks = chunk_transcript(make_transcript(turns(20)), target_tokens=250)

    for chunk in chunks:
        assert chunk.start_s <= chunk.end_s


def test_rejects_a_target_larger_than_the_ceiling():
    with pytest.raises(ValueError, match="target_tokens"):
        chunk_transcript(make_transcript(turns(4)), target_tokens=600, max_tokens=500)


@pytest.mark.parametrize(
    ("seconds", "expected"), [(0, "00:00:00"), (65, "00:01:05"), (3725, "01:02:05")]
)
def test_formats_timestamps(seconds, expected):
    assert format_timestamp(seconds) == expected


def test_token_estimate_is_never_zero():
    assert estimate_tokens("") == 1
