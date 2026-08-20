"""Per-meeting structured extraction: summary, decisions, action items.

Two things make this more trustworthy than asking a model for JSON and hoping.

**Decoding is constrained.** Ollama takes a JSON schema and restricts token
selection to it, so the output parses by construction. A 12B model asked
politely for JSON produces prose with a code fence often enough to matter; asked
under a schema, it cannot.

**Every extracted item carries a verbatim quote, which is matched back against
the transcript.** If the model invents an action item, its quote will not appear
in any turn, and the item is stored with a null `utterance_seq`. That mismatch
is the signal — it converts "the model might be making things up" from a worry
into something countable. See `docs/MEASUREMENTS.md` for the rate on the seed
corpus.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from meetingiq.config import Settings
from meetingiq.ingest.chunker import estimate_tokens
from meetingiq.llm.base import LLMProvider, ProviderError
from meetingiq.models import ActionItem, Decision, Meeting, Utterance

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You read a meeting transcript and extract what it recorded.

For every decision and every action item, include a `quote`: the speaker's own
words, copied exactly from the transcript, that show it. Copy the words — do not
paraphrase them, and do not write a quote for anything the transcript does not
say.

A decision is something the group settled, not something they discussed. An
action item is a commitment by a named person to do a specific thing. If a
meeting settled nothing, return an empty list — that is a normal outcome, not a
failure to find something.

For `due`, copy the deadline as it was said — "by Friday", "the 14th of August",
"before GA". Use an empty string when no deadline was given. Do not invent one.

For `owner`, name the person who has to do the thing, which is not always the
person who said it: someone assigning work names the owner, not themselves."""

# Constrains decoding, so the response parses by construction.
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["text", "quote"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "description": {"type": "string"},
                    "due": {"type": "string"},
                    "quote": {"type": "string"},
                },
                # `due` is required so the model always emits it; the prompt
                # tells it to use an empty string when no deadline was given.
                # Left optional, it was omitted every single time.
                "required": ["owner", "description", "due", "quote"],
            },
        },
    },
    "required": ["summary", "decisions", "action_items"],
}


@dataclass(frozen=True, slots=True)
class GroundingStats:
    """How much of what the model produced could be found in the transcript."""

    total: int
    grounded: int
    ungrounded_quotes: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float | None:
        """None when nothing was measured — a cached read checks no quotes.

        Returning 1.0 there would report a perfect score for work that never
        happened, which is exactly the kind of flattering metric this whole
        mechanism exists to avoid.
        """
        return self.grounded / self.total if self.total else None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    meeting_id: str
    summary: str
    decision_count: int
    action_count: int
    grounding: GroundingStats
    duration_ms: int
    cached: bool = False


def _normalise(text: str) -> str:
    """Fold the differences that should not count as a mismatch.

    Models reliably change smart quotes to straight ones, collapse whitespace,
    and drop a trailing full stop. None of those mean the quote was invented.
    """
    text = text.casefold()
    # These are the characters being normalised away, so ruff's
    # ambiguous-unicode warning is exactly backwards here.
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    return re.sub(r"[^a-z0-9' ]+", " ", re.sub(r"\s+", " ", text)).strip()


def match_quote(quote: str, utterances: list[Utterance]) -> Utterance | None:
    """Find the turn a quote came from, or None if it is not in the transcript.

    Containment either way: models truncate a long turn, and they also
    occasionally stitch a quote from two adjacent sentences of one.
    """
    needle = _normalise(quote)
    # Too short to be evidence of anything — "yes" appears everywhere.
    if len(needle) < 12:
        return None

    for utterance in utterances:
        haystack = _normalise(utterance.text)
        if needle in haystack or haystack in needle:
            return utterance
    return None


def canonical_owner(owner: str, speakers: list[str]) -> str:
    """Resolve an owner name against the people who actually spoke.

    The model writes "Dana Osei" in one meeting and "Dana" in the next, which
    splits one person into two rows on a board whose entire job is answering
    "who owes what". A first name resolves only when exactly one speaker has it
    — with two Danas in the room, guessing would silently assign work to the
    wrong person, which is worse than leaving the name as written.
    """
    cleaned = re.sub(r"\s+", " ", owner).strip()
    if not cleaned:
        return owner

    folded = cleaned.casefold()
    for speaker in speakers:
        if speaker.casefold() == folded:
            return speaker

    matches = [s for s in speakers if s.split()[0].casefold() == folded]
    return matches[0] if len(matches) == 1 else cleaned


def _render_transcript(utterances: list[Utterance]) -> str:
    return "\n".join(f"[{u.seq}] {u.speaker}: {u.text}" for u in utterances)


def extract_brief(
    session: Session,
    *,
    meeting_id: str,
    settings: Settings,
    llm: LLMProvider,
    force: bool = False,
) -> ExtractionResult:
    """Extract a meeting's brief, caching the result on the meeting row."""
    started = time.perf_counter()

    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise LookupError(f"no meeting {meeting_id}")

    if meeting.extracted_at is not None and not force:
        return ExtractionResult(
            meeting_id=str(meeting.id),
            summary=meeting.summary or "",
            decision_count=len(meeting.decisions),
            action_count=len(meeting.action_items),
            grounding=GroundingStats(total=0, grounded=0),
            duration_ms=0,
            cached=True,
        )

    utterances = list(
        session.scalars(
            select(Utterance).where(Utterance.meeting_id == meeting.id).order_by(Utterance.seq)
        ).all()
    )
    transcript = _render_transcript(utterances)

    # The seed corpus's longest meeting is ~8K tokens, well inside the window.
    # Truncating silently would produce a brief that omits the end of a meeting
    # while looking complete, so this refuses instead.
    budget = settings.num_ctx - estimate_tokens(SYSTEM_PROMPT) - settings.max_answer_tokens - 512
    if estimate_tokens(transcript) > budget:
        raise ProviderError(
            f"transcript is ~{estimate_tokens(transcript)} tokens, over the "
            f"{budget} available for extraction; map-reduce over chunks is the fix"
        )

    raw = llm.generate(
        system=SYSTEM_PROMPT,
        prompt=f"Transcript of {meeting.title}:\n\n{transcript}",
        max_tokens=settings.max_answer_tokens,
        schema=SCHEMA,
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"extraction did not return JSON: {exc}") from exc

    # A forced re-extraction replaces rather than accumulates.
    for existing in [*meeting.decisions, *meeting.action_items]:
        session.delete(existing)
    session.flush()

    total = 0
    grounded = 0
    ungrounded: list[str] = []

    for index, item in enumerate(payload.get("decisions", [])):
        turn = match_quote(item.get("quote", ""), utterances)
        total += 1
        if turn:
            grounded += 1
        else:
            ungrounded.append(item.get("quote", "")[:120])
        session.add(
            Decision(
                meeting_id=meeting.id,
                seq=index,
                text=item["text"],
                quote=item.get("quote", ""),
                utterance_seq=turn.seq if turn else None,
                speaker=turn.speaker if turn else None,
                start_s=turn.start_s if turn else None,
            )
        )

    # Corpus-wide, not just this meeting's speakers: people are given work in
    # meetings they did not attend, and the action board is cross-meeting — an
    # owner resolved differently in two meetings appears as two people on it.
    speakers = list(session.scalars(select(Utterance.speaker).distinct()).all())
    for index, item in enumerate(payload.get("action_items", [])):
        turn = match_quote(item.get("quote", ""), utterances)
        total += 1
        if turn:
            grounded += 1
        else:
            ungrounded.append(item.get("quote", "")[:120])
        session.add(
            ActionItem(
                meeting_id=meeting.id,
                seq=index,
                description=item["description"],
                owner=canonical_owner(item["owner"], speakers),
                due=item.get("due") or None,
                quote=item.get("quote", ""),
                utterance_seq=turn.seq if turn else None,
                speaker=turn.speaker if turn else None,
                start_s=turn.start_s if turn else None,
            )
        )

    meeting.summary = payload.get("summary", "")
    meeting.extracted_at = datetime.now(UTC)
    session.commit()

    stats = GroundingStats(total=total, grounded=grounded, ungrounded_quotes=ungrounded)
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "extracted meeting brief",
        extra={
            "meeting_id": str(meeting.id),
            "decisions": len(payload.get("decisions", [])),
            "actions": len(payload.get("action_items", [])),
            "grounding_rate": round(stats.rate, 3) if stats.rate is not None else None,
            "duration_ms": duration_ms,
        },
    )
    if stats.ungrounded_quotes:
        logger.warning(
            "extracted quotes that are not in the transcript",
            extra={"meeting_id": str(meeting.id), "quotes": stats.ungrounded_quotes},
        )

    return ExtractionResult(
        meeting_id=str(meeting.id),
        summary=meeting.summary,
        decision_count=len(payload.get("decisions", [])),
        action_count=len(payload.get("action_items", [])),
        grounding=stats,
        duration_ms=duration_ms,
    )
