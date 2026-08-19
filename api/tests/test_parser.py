"""Parser tests.

Concentrated on the contract in seed/FORMAT.md: whatever the input format, the
output is an ordered list of (speaker, start, end, text), and anything
unparseable raises rather than silently losing lines.
"""

import pytest

from meetingiq.ingest.parser import (
    TranscriptFormat,
    TranscriptParseError,
    detect_format,
    parse_timestamp,
    parse_transcript,
)

BRACKETED = """\
# Meeting: Weekly Sync
# Date: 2026-03-04
# Duration: 00:30:00
# Participants: Ada Lovelace, Alan Turing

[00:00:05] Ada Lovelace: Morning all.
[00:01:10] Alan Turing: Morning.
"""

PARENTHESISED = """\
Ada Lovelace (00:00:05): Morning all.
Alan Turing (1:10): Morning.
"""

WEBVTT = """\
WEBVTT

NOTE Meeting: Weekly Sync
NOTE Date: 2026-03-04

1
00:00:05.000 --> 00:00:12.500
Ada Lovelace: Morning all.

2
00:01:10.000 --> 00:01:14.000
Alan Turing: Morning.
"""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (BRACKETED, TranscriptFormat.BRACKETED),
        (PARENTHESISED, TranscriptFormat.PARENTHESISED),
        (WEBVTT, TranscriptFormat.WEBVTT),
    ],
)
def test_detects_each_format(raw, expected):
    assert detect_format(raw) is expected


@pytest.mark.parametrize("raw", [BRACKETED, PARENTHESISED, WEBVTT])
def test_all_formats_yield_the_same_utterances(raw):
    """The whole point of supporting three formats is that they converge."""
    transcript = parse_transcript(raw, filename="2026-03-04-weekly-sync.txt")

    assert [(u.speaker, u.start_s, u.text) for u in transcript.utterances] == [
        ("Ada Lovelace", 5.0, "Morning all."),
        ("Alan Turing", 70.0, "Morning."),
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("00:00:05", 5.0), ("1:10", 70.0), ("01:02:03", 3723.0), ("00:00:12.500", 12.5)],
)
def test_parses_timestamps(value, expected):
    assert parse_timestamp(value) == expected


def test_rejects_unparseable_timestamp():
    with pytest.raises(TranscriptParseError):
        parse_timestamp("half past two")


def test_reads_header_metadata():
    transcript = parse_transcript(BRACKETED, filename="anything.txt")

    assert transcript.title == "Weekly Sync"
    assert transcript.meeting_date.isoformat() == "2026-03-04"
    assert transcript.duration_s == 1800.0
    assert transcript.participants == ["Ada Lovelace", "Alan Turing"]


def test_falls_back_to_filename_when_there_is_no_header():
    """Format B carries no metadata, so the filename has to carry it."""
    transcript = parse_transcript(PARENTHESISED, filename="2026-03-04-weekly-sync.txt")

    assert transcript.title == "Weekly Sync"
    assert transcript.meeting_date.isoformat() == "2026-03-04"
    # Derived from who actually spoke.
    assert transcript.participants == ["Ada Lovelace", "Alan Turing"]


def test_joins_utterances_that_wrap_across_lines():
    raw = """\
[00:00:05] Ada Lovelace: This is a long thought that
continues on the next line.
[00:00:20] Alan Turing: Quite.
"""
    transcript = parse_transcript(raw)

    assert (
        transcript.utterances[0].text == "This is a long thought that continues on the next line."
    )
    assert len(transcript.utterances) == 2


def test_continuation_before_any_utterance_is_an_error():
    """Silently dropping it would lose content with no trace."""
    with pytest.raises(TranscriptParseError, match="continuation text"):
        parse_transcript("stray line\n[00:00:05] Ada Lovelace: Morning.\n")


def test_rejects_input_with_no_recognisable_format():
    with pytest.raises(TranscriptParseError, match="could not detect"):
        parse_transcript("just some prose with no speakers or timestamps")


def test_rejects_empty_transcript():
    with pytest.raises(TranscriptParseError):
        parse_transcript("WEBVTT\n")


def test_collapses_case_variants_of_the_same_speaker():
    raw = "[00:00:05] ada lovelace: One.\n[00:00:10] Ada Lovelace: Two.\n"

    transcript = parse_transcript(raw)

    # First spelling seen wins, so output is stable.
    assert {u.speaker for u in transcript.utterances} == {"ada lovelace"}


def test_does_not_merge_a_first_name_with_a_full_name():
    """Guessing that 'Ada' is 'Ada Lovelace' is a judgement, not a parse."""
    raw = "[00:00:05] Ada: One.\n[00:00:10] Ada Lovelace: Two.\n"

    transcript = parse_transcript(raw)

    assert {u.speaker for u in transcript.utterances} == {"Ada", "Ada Lovelace"}


def test_end_time_is_the_next_utterances_start():
    transcript = parse_transcript(BRACKETED)

    assert transcript.utterances[0].end_s == 70.0


def test_final_utterance_does_not_stretch_to_the_meeting_duration():
    """A transcript is often an excerpt; the last turn is not 29 minutes long."""
    transcript = parse_transcript(BRACKETED)

    last = transcript.utterances[-1]
    assert last.end_s < 120.0, "final utterance should end when speaking stops"
    assert transcript.duration_s == 1800.0


def test_webvtt_keeps_real_cue_end_times():
    """WebVTT is the only format carrying one, so it must not be discarded."""
    transcript = parse_transcript(WEBVTT)

    assert transcript.utterances[0].end_s == 12.5


def test_webvtt_cue_without_a_speaker_prefix_is_an_error():
    raw = "WEBVTT\n\n1\n00:00:05.000 --> 00:00:10.000\nno speaker here\n"

    with pytest.raises(TranscriptParseError, match="Speaker"):
        parse_transcript(raw)


def test_utterances_are_renumbered_from_zero():
    transcript = parse_transcript(BRACKETED)

    assert [u.seq for u in transcript.utterances] == [0, 1]
