"""Speaker-aware chunking.

Fixed-size token windows are the wrong unit for a meeting. They cut through the
middle of a sentence someone was still saying, and they throw away the one thing
that makes transcript data distinctive: who was speaking, and when.

So chunks are built from whole speaker turns. A chunk grows until adding the
next turn would exceed the target, then closes. Turns are never split — except
where a single turn is longer than the hard ceiling on its own, which falls back
to sentence boundaries rather than producing a chunk too coarse to retrieve
precisely.

Each chunk carries one turn of overlap with the previous one, because pronouns
do not respect chunk boundaries: "he said we should revisit that" is
unresolvable without the turn before it.
"""

import re
from dataclasses import dataclass

from meetingiq.ingest.parser import ParsedTranscript, Utterance

# Terminal punctuation followed by whitespace.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def estimate_tokens(text: str) -> int:
    """Approximate token count.

    Deliberately an estimate. Counting Gemma tokens exactly means either a
    network round-trip per chunk — far too slow at ingest — or shipping the
    tokenizer and its vocabulary as a dependency. The standard ~4-characters-
    per-token heuristic is close enough given the downstream context budget is
    set conservatively (12K against a 32K window), so estimation error cannot
    cause the silent truncation that budget exists to prevent.
    """
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True, slots=True)
class Chunk:
    seq: int
    text: str
    context_header: str
    speakers: list[str]
    start_s: float
    end_s: float
    utterance_seqs: list[int]
    token_estimate: int

    def embedding_input(self, meeting_title: str) -> str:
        """Text as handed to the embedding model.

        EmbeddingGemma is asymmetric — documents and queries take different
        prefixes — and its documented document form is
        `title: {title} | text: {content}`. The meeting title is a real title,
        which the model card notes performs better than the "none" placeholder.
        The context header goes inside the text so the vector carries date,
        speakers and time range as well as content.
        """
        return f"title: {meeting_title} | text: {self.context_header}\n{self.text}"


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _render(utterances: list[Utterance]) -> str:
    """Speaker names stay inline so full-text search can match on them."""
    return "\n".join(f"{u.speaker}: {u.text}" for u in utterances)


def _build_header(transcript: ParsedTranscript, utterances: list[Utterance]) -> str:
    speakers = list(dict.fromkeys(u.speaker for u in utterances))
    parts = [f"Meeting: {transcript.title}"]
    if transcript.meeting_date:
        parts.append(f"Date: {transcript.meeting_date.isoformat()}")
    parts.append(f"Speakers: {', '.join(speakers)}")
    start, end = utterances[0].start_s, utterances[-1].end_s
    parts.append(f"{format_timestamp(start)}-{format_timestamp(end)}")
    return " | ".join(parts)


def _split_long_utterance(utterance: Utterance, max_tokens: int) -> list[Utterance]:
    """Split a single over-long turn on sentence boundaries.

    Only reached when one person talks for longer than a whole chunk allows.
    Keeping it intact would produce a chunk too coarse to retrieve precisely;
    splitting mid-sentence would produce fragments that read as broken. Every
    piece keeps the original speaker, timing and seq, so citations still resolve
    to the turn that was actually spoken.
    """
    # Budget against the rendered form: the chunk this ends up in is measured
    # with the "Speaker: " prefix applied, so splitting on the raw text alone
    # overflows by the width of the speaker name.
    prefix_tokens = estimate_tokens(f"{utterance.speaker}: ")
    budget = max(1, max_tokens - prefix_tokens)

    pieces: list[Utterance] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            pieces.append(
                Utterance(
                    seq=utterance.seq,
                    speaker=utterance.speaker,
                    start_s=utterance.start_s,
                    end_s=utterance.end_s,
                    text=" ".join(current),
                )
            )
            current.clear()

    for sentence in _SENTENCE_BOUNDARY.split(utterance.text):
        if current and estimate_tokens(" ".join([*current, sentence])) > budget:
            flush()
        current.append(sentence)
    flush()
    return pieces or [utterance]


def chunk_transcript(
    transcript: ParsedTranscript,
    *,
    target_tokens: int = 350,
    max_tokens: int = 500,
    overlap_turns: int = 1,
) -> list[Chunk]:
    """Group utterances into overlapping, speaker-aware chunks."""
    if target_tokens > max_tokens:
        raise ValueError("target_tokens must not exceed max_tokens")

    # Expand any turn too long to fit in a chunk by itself up front, so the main
    # loop only ever handles utterances that do fit.
    units: list[Utterance] = []
    for utterance in transcript.utterances:
        if estimate_tokens(utterance.text) > max_tokens:
            units.extend(_split_long_utterance(utterance, max_tokens))
        else:
            units.append(utterance)

    chunks: list[Chunk] = []
    current: list[Utterance] = []

    def close() -> None:
        if not current:
            return
        text = _render(current)
        chunks.append(
            Chunk(
                seq=len(chunks),
                text=text,
                context_header=_build_header(transcript, current),
                speakers=list(dict.fromkeys(u.speaker for u in current)),
                start_s=current[0].start_s,
                end_s=current[-1].end_s,
                # dict.fromkeys keeps order while collapsing the duplicate seqs
                # a split long turn produces.
                utterance_seqs=list(dict.fromkeys(u.seq for u in current)),
                token_estimate=estimate_tokens(text),
            )
        )

    for unit in units:
        if current and estimate_tokens(_render([*current, unit])) > target_tokens:
            close()
            # Carry the tail forward so pronouns resolve — but never so much
            # that the new chunk starts already full, which would stall the loop.
            carry = current[-overlap_turns:] if overlap_turns else []
            if estimate_tokens(_render([*carry, unit])) > target_tokens:
                carry = []
            current = [*carry, unit]
        else:
            current.append(unit)

    close()
    return chunks
