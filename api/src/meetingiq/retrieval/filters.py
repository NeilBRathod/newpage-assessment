"""Extracting metadata filters from a question.

"What did Dana say about reconciliation?" carries two separable things: a
semantic query ("reconciliation") and a hard constraint (speaker = Dana). Dense
retrieval handles the first well and the second badly — an embedding cannot
express "only these rows".

These filters are derived by matching the question against speakers and meeting
titles that actually exist in the corpus, rather than by asking an LLM. A lookup
against known values costs no tokens, adds no latency, and cannot invent a
speaker who was never in the room. The cost is that it only catches names as
written; "the VP of engineering" will not resolve to Priya. That is an accepted
limit, not an oversight — an LLM extraction pass is the upgrade path if the
misses turn out to matter.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from meetingiq.models import Meeting, Utterance


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    meeting_ids: list[str] = field(default_factory=list)
    speakers: list[str] = field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.meeting_ids or self.speakers or self.date_from or self.date_to)

    def describe(self) -> str:
        parts = []
        if self.speakers:
            parts.append(f"speakers={self.speakers}")
        if self.meeting_ids:
            parts.append(f"meetings={len(self.meeting_ids)}")
        if self.date_from or self.date_to:
            parts.append(f"dates={self.date_from}..{self.date_to}")
        return ", ".join(parts) or "none"


def _word_boundary_match(needle: str, haystack: str) -> bool:
    return re.search(rf"\b{re.escape(needle)}\b", haystack, flags=re.IGNORECASE) is not None


def extract_filters(
    session: Session, question: str, *, known_speakers: list[str] | None = None
) -> RetrievalFilters:
    """Match a question against speakers and meeting titles present in the corpus."""
    if known_speakers is None:
        # Who actually spoke, rather than who a header claimed was invited.
        known_speakers = list(session.scalars(select(Utterance.speaker).distinct()).all())

    matched_speakers: list[str] = []
    for speaker in known_speakers:
        # Full name first, then first name — "Dana" should find Dana Osei, but
        # only when no other speaker shares that first name, otherwise the
        # filter would silently exclude one of them.
        if _word_boundary_match(speaker, question):
            matched_speakers.append(speaker)
            continue
        first_name = speaker.split()[0]
        others = [s for s in known_speakers if s != speaker and s.split()[0] == first_name]
        if not others and _word_boundary_match(first_name, question):
            matched_speakers.append(speaker)

    matched_meetings: list[str] = []
    for meeting_id, title in session.execute(select(Meeting.id, Meeting.title)):
        # Require a distinctive title, not a stopword like "Review", to avoid
        # a generic word collapsing retrieval onto one meeting.
        if len(title) >= 8 and title.casefold() in question.casefold():
            matched_meetings.append(str(meeting_id))

    return RetrievalFilters(meeting_ids=matched_meetings, speakers=matched_speakers)
