"""Transcript parsing.

Three input formats, one output contract: an ordered list of utterances, each
with a speaker, a start time in seconds, an end time, and text. See
seed/FORMAT.md for the formats themselves.

The guiding rule is that unparseable input raises rather than being skipped. A
transcript that silently loses a third of its lines is far worse than one that
refuses to load, because the loss shows up much later as a confidently wrong
answer with nothing to trace it back to.
"""

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import PurePath

# Words per second of speech, used only to estimate the end of the final
# utterance when a format gives no duration. Conversational English runs at
# roughly 150 wpm.
_WORDS_PER_SECOND = 2.5
_MIN_UTTERANCE_SECONDS = 2.0


class TranscriptFormat(StrEnum):
    BRACKETED = "bracketed"  # [00:00:04] Speaker: text
    PARENTHESISED = "parenthesised"  # Speaker (00:00:04): text
    WEBVTT = "webvtt"


class TranscriptParseError(ValueError):
    """Raised when input cannot be parsed into utterances."""


@dataclass(frozen=True, slots=True)
class Utterance:
    seq: int
    speaker: str
    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True, slots=True)
class ParsedTranscript:
    title: str
    meeting_date: date | None
    duration_s: float | None
    participants: list[str]
    source_format: TranscriptFormat
    utterances: list[Utterance]


# --- shared helpers -------------------------------------------------------

_TIMESTAMP = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d{1,3})?"
_BRACKETED_LINE = re.compile(rf"^\[\s*({_TIMESTAMP})\s*\]\s*([^:]{{1,120}}?)\s*:\s*(.*)$")
_PARENTHESISED_LINE = re.compile(rf"^([^:(\n]{{1,120}}?)\s*\(\s*({_TIMESTAMP})\s*\)\s*:\s*(.*)$")
_HEADER_LINE = re.compile(r"^#\s*([A-Za-z ]+)\s*:\s*(.*)$")
_VTT_NOTE = re.compile(r"^NOTE\s+([A-Za-z ]+)\s*:\s*(.*)$")
_VTT_CUE_TIMING = re.compile(rf"^({_TIMESTAMP})\s*-->\s*({_TIMESTAMP})")
_VTT_CUE_SPEAKER = re.compile(r"^([^:\n]{1,120}?)\s*:\s*(.*)$")
_DATE_IN_FILENAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def parse_timestamp(value: str) -> float:
    """`HH:MM:SS(.mmm)` or `MM:SS(.mmm)` to seconds."""
    parts = value.strip().split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, (minutes, seconds) = "0", parts
    else:
        raise TranscriptParseError(f"unrecognised timestamp: {value!r}")
    try:
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError as exc:
        raise TranscriptParseError(f"unrecognised timestamp: {value!r}") from exc


def detect_format(text: str) -> TranscriptFormat:
    if text.lstrip().startswith("WEBVTT"):
        return TranscriptFormat.WEBVTT
    for line in text.splitlines():
        if _BRACKETED_LINE.match(line):
            return TranscriptFormat.BRACKETED
        if _PARENTHESISED_LINE.match(line):
            return TranscriptFormat.PARENTHESISED
    raise TranscriptParseError(
        "could not detect transcript format: no WEBVTT header, bracketed "
        "'[00:00:00] Speaker:' lines, or 'Speaker (00:00:00):' lines found"
    )


def _canonicalise_speakers(raw_names: list[str]) -> dict[str, str]:
    """Map each spelling of a name to one canonical form.

    Case differences collapse ("dana osei" and "Dana Osei" are one person).
    Anything more than that — deciding "Dana" and "Dana Osei" are the same
    person — is a judgement the system should not make silently, so it doesn't.
    """
    canonical: dict[str, str] = {}
    for name in raw_names:
        cleaned = re.sub(r"\s+", " ", name).strip()
        key = cleaned.casefold()
        # First spelling seen wins, so output is stable and predictable.
        canonical.setdefault(key, cleaned)
    return canonical


def _finalise(
    rows: list[tuple[str, float, float | None, str]],
    duration_s: float | None,
) -> list[Utterance]:
    """Assign end times, canonicalise speakers, renumber from zero.

    Where a format carries no end time, an utterance ends when the next one
    begins. The final utterance falls back to the meeting duration, or to an
    estimate from its own word count when there isn't one.
    """
    if not rows:
        raise TranscriptParseError("transcript contains no utterances")

    canonical = _canonicalise_speakers([speaker for speaker, _, _, _ in rows])

    utterances: list[Utterance] = []
    for index, (speaker, start_s, end_s, text) in enumerate(rows):
        if end_s is None:
            if index + 1 < len(rows):
                end_s = rows[index + 1][1]
            else:
                # The last utterance ends when speaking plausibly stops, not when
                # the meeting does. Transcripts are often excerpts, so trusting
                # the header duration here would stretch the final turn — and the
                # chunk containing it — across tens of minutes of silence.
                spoken = len(text.split()) / _WORDS_PER_SECOND
                end_s = start_s + max(spoken, _MIN_UTTERANCE_SECONDS)
                if duration_s is not None and start_s < duration_s < end_s:
                    end_s = duration_s
        utterances.append(
            Utterance(
                seq=index,
                speaker=canonical[re.sub(r"\s+", " ", speaker).strip().casefold()],
                start_s=start_s,
                end_s=max(end_s, start_s),
                text=text.strip(),
            )
        )
    return utterances


def _title_from_filename(filename: str) -> str:
    stem = PurePath(filename).stem
    stem = _DATE_IN_FILENAME.sub("", stem).strip("-_ ")
    return stem.replace("-", " ").replace("_", " ").strip().title() or "Untitled meeting"


def _date_from_filename(filename: str) -> date | None:
    match = _DATE_IN_FILENAME.search(PurePath(filename).name)
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def _coerce_metadata(
    headers: dict[str, str], filename: str
) -> tuple[str, date | None, float | None, list[str]]:
    title = headers.get("meeting") or _title_from_filename(filename)

    meeting_date: date | None = None
    if raw_date := headers.get("date"):
        try:
            meeting_date = date.fromisoformat(raw_date.strip())
        except ValueError as exc:
            raise TranscriptParseError(f"unrecognised date in header: {raw_date!r}") from exc
    else:
        meeting_date = _date_from_filename(filename)

    duration_s = parse_timestamp(headers["duration"]) if headers.get("duration") else None

    participants = [
        name.strip() for name in headers.get("participants", "").split(",") if name.strip()
    ]
    return title, meeting_date, duration_s, participants


# --- format parsers -------------------------------------------------------


def _parse_line_oriented(
    text: str, filename: str, pattern: re.Pattern[str], fmt: TranscriptFormat
) -> ParsedTranscript:
    """Formats A and B: one utterance per line, with `# Key: value` headers.

    Lines that match neither a header nor the utterance pattern are treated as
    continuations of the utterance above, which is how long turns wrap in real
    exports. A continuation before any utterance is an error, not a shrug.
    """
    headers: dict[str, str] = {}
    rows: list[tuple[str, float, float | None, str]] = []

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        if not line.strip():
            continue

        if header := _HEADER_LINE.match(line):
            headers[header[1].strip().casefold()] = header[2].strip()
            continue

        if match := pattern.match(line):
            if fmt is TranscriptFormat.BRACKETED:
                timestamp, speaker, body = match[1], match[2], match[3]
            else:
                speaker, timestamp, body = match[1], match[2], match[3]
            rows.append((speaker, parse_timestamp(timestamp), None, body.strip()))
            continue

        if not rows:
            raise TranscriptParseError(
                f"line {lineno}: continuation text before any utterance: {line[:60]!r}"
            )
        speaker, start_s, end_s, body = rows[-1]
        rows[-1] = (speaker, start_s, end_s, f"{body} {line.strip()}")

    title, meeting_date, duration_s, participants = _coerce_metadata(headers, filename)
    utterances = _finalise(rows, duration_s)
    if not participants:
        participants = sorted({utterance.speaker for utterance in utterances})

    return ParsedTranscript(
        title=title,
        meeting_date=meeting_date,
        duration_s=duration_s,
        participants=participants,
        source_format=fmt,
        utterances=utterances,
    )


def _parse_webvtt(text: str, filename: str) -> ParsedTranscript:
    """Format C. The only format carrying real cue end times, which are kept."""
    headers: dict[str, str] = {}
    rows: list[tuple[str, float, float | None, str]] = []

    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        if lines[0].strip() == "WEBVTT" or lines[0].startswith("NOTE"):
            for line in lines:
                if note := _VTT_NOTE.match(line):
                    headers[note[1].strip().casefold()] = note[2].strip()
            continue

        # An optional cue identifier may precede the timing line.
        timing_index = 0 if _VTT_CUE_TIMING.match(lines[0]) else 1
        if timing_index >= len(lines) or not (timing := _VTT_CUE_TIMING.match(lines[timing_index])):
            raise TranscriptParseError(f"WebVTT cue has no timing line: {lines[0][:60]!r}")

        payload = " ".join(line.strip() for line in lines[timing_index + 1 :])
        speaker_match = _VTT_CUE_SPEAKER.match(payload)
        if not speaker_match:
            raise TranscriptParseError(
                f"WebVTT cue text has no 'Speaker:' prefix: {payload[:60]!r}"
            )

        rows.append(
            (
                speaker_match[1],
                parse_timestamp(timing[1]),
                parse_timestamp(timing[2]),
                speaker_match[2].strip(),
            )
        )

    title, meeting_date, duration_s, participants = _coerce_metadata(headers, filename)
    utterances = _finalise(rows, duration_s)
    if not participants:
        participants = sorted({utterance.speaker for utterance in utterances})

    return ParsedTranscript(
        title=title,
        meeting_date=meeting_date,
        duration_s=duration_s,
        participants=participants,
        source_format=TranscriptFormat.WEBVTT,
        utterances=utterances,
    )


def parse_transcript(text: str, *, filename: str = "") -> ParsedTranscript:
    """Parse a transcript in any supported format."""
    fmt = detect_format(text)
    if fmt is TranscriptFormat.WEBVTT:
        return _parse_webvtt(text, filename)
    pattern = _BRACKETED_LINE if fmt is TranscriptFormat.BRACKETED else _PARENTHESISED_LINE
    return _parse_line_oriented(text, filename, pattern, fmt)
