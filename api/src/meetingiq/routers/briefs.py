"""Per-meeting briefs and the cross-meeting action board.

Extraction is lazy and cached. A full-transcript pass costs roughly a minute on
a local model, so doing it for every meeting at ingest would turn `make seed`
into an eight-minute wait for something most questions never need. The first
request for a brief pays that cost once; everything after reads from Postgres.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from meetingiq.config import Settings, get_settings
from meetingiq.db import get_session
from meetingiq.extraction.brief import extract_brief
from meetingiq.llm.base import LLMProvider, ProviderError
from meetingiq.models import ActionItem, Meeting
from meetingiq.routers.chat import llm_provider
from meetingiq.routers.meetings import summarise
from meetingiq.schemas import ActionBoard, ActionItemOut, BriefOut, DecisionOut, OwnerActions

logger = logging.getLogger(__name__)
router = APIRouter(tags=["briefs"])


def _action_out(item: ActionItem, meeting: Meeting) -> ActionItemOut:
    return ActionItemOut(
        id=str(item.id),
        description=item.description,
        owner=item.owner,
        due=item.due,
        quote=item.quote,
        utterance_seq=item.utterance_seq,
        speaker=item.speaker,
        start_s=item.start_s,
        meeting_id=str(meeting.id),
        meeting_title=meeting.title,
        meeting_date=meeting.meeting_date.isoformat() if meeting.meeting_date else None,
    )


@router.get("/meetings/{meeting_id}/brief", response_model=BriefOut)
def get_brief(
    meeting_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    llm: Annotated[LLMProvider, Depends(llm_provider)],
    refresh: Annotated[bool, Query(description="Re-extract even if cached")] = False,
) -> BriefOut:
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")

    if meeting.extracted_at is None or refresh:
        try:
            extract_brief(session, meeting_id=meeting_id, settings=settings, llm=llm, force=refresh)
        except ProviderError as exc:
            # 503 rather than 500: the model is a dependency that can be down or
            # over its context budget, and that is not a bug in this service.
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        session.refresh(meeting)

    decisions = [
        DecisionOut(
            id=str(d.id),
            text=d.text,
            quote=d.quote,
            utterance_seq=d.utterance_seq,
            speaker=d.speaker,
            start_s=d.start_s,
        )
        for d in meeting.decisions
    ]
    actions = [_action_out(a, meeting) for a in meeting.action_items]
    items = [*decisions, *actions]

    return BriefOut(
        meeting=summarise(meeting),
        summary=meeting.summary or "",
        decisions=decisions,
        action_items=actions,
        extracted_at=meeting.extracted_at.isoformat() if meeting.extracted_at else None,
        grounded_count=sum(1 for i in items if i.utterance_seq is not None),
        total_count=len(items),
    )


@router.get("/actions", response_model=ActionBoard)
def action_board(session: Annotated[Session, Depends(get_session)]) -> ActionBoard:
    """Every extracted action item, grouped by owner.

    Reads only what has already been extracted — it does not trigger extraction
    for meetings that have none, because doing so would make one request take
    eight minutes.
    """
    rows = session.execute(
        select(ActionItem, Meeting)
        .join(Meeting, Meeting.id == ActionItem.meeting_id)
        .order_by(Meeting.meeting_date, ActionItem.seq)
    ).all()

    by_owner: dict[str, list[ActionItemOut]] = {}
    for item, meeting in rows:
        by_owner.setdefault(item.owner, []).append(_action_out(item, meeting))

    owners = [
        OwnerActions(owner=owner, items=items)
        # Most commitments first; it is the question the board answers.
        for owner, items in sorted(by_owner.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    total = sum(len(o.items) for o in owners)
    return ActionBoard(
        owners=owners,
        total=total,
        ungrounded=sum(1 for o in owners for i in o.items if i.utterance_seq is None),
    )
