"""Meeting listing and transcript retrieval.

The transcript endpoint exists for the evidence panel: a citation is only
trustworthy if the user can click it and read the surrounding conversation.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from meetingiq.db import get_session
from meetingiq.models import Meeting, Utterance
from meetingiq.schemas import MeetingSummary, TranscriptOut, UtteranceOut

router = APIRouter(prefix="/meetings", tags=["meetings"])


def summarise(meeting: Meeting) -> MeetingSummary:
    return MeetingSummary(
        id=str(meeting.id),
        title=meeting.title,
        meeting_date=meeting.meeting_date.isoformat() if meeting.meeting_date else None,
        participants=list(meeting.participants),
        duration_s=meeting.duration_s,
        utterance_count=meeting.utterance_count,
        chunk_count=meeting.chunk_count,
        source_format=meeting.source_format,
    )


@router.get("", response_model=list[MeetingSummary])
def list_meetings(session: Annotated[Session, Depends(get_session)]) -> list[MeetingSummary]:
    meetings = session.scalars(
        # Newest first, but undated meetings should not sort to the top.
        select(Meeting).order_by(Meeting.meeting_date.desc().nullslast(), Meeting.created_at.desc())
    ).all()
    return [summarise(meeting) for meeting in meetings]


@router.get("/{meeting_id}/transcript", response_model=TranscriptOut)
def get_transcript(
    meeting_id: UUID, session: Annotated[Session, Depends(get_session)]
) -> TranscriptOut:
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")

    utterances = session.scalars(
        select(Utterance).where(Utterance.meeting_id == meeting_id).order_by(Utterance.seq)
    ).all()

    return TranscriptOut(
        meeting=summarise(meeting),
        utterances=[
            UtteranceOut(
                seq=u.seq, speaker=u.speaker, start_s=u.start_s, end_s=u.end_s, text=u.text
            )
            for u in utterances
        ],
    )


@router.get("/stats/corpus")
def corpus_stats(session: Annotated[Session, Depends(get_session)]) -> dict:
    """Small enough to be honest about: what is actually loaded."""
    return {
        "meetings": session.scalar(select(func.count()).select_from(Meeting)) or 0,
        "utterances": session.scalar(select(func.count()).select_from(Utterance)) or 0,
        "speakers": session.scalar(select(func.count(func.distinct(Utterance.speaker)))) or 0,
    }
