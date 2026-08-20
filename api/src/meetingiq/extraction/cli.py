"""`python -m meetingiq.extraction.cli` — warm every meeting's brief.

Extraction is lazy by default: the first request for a brief runs the model over
the whole transcript, which takes about half a minute locally. That keeps
`make seed` fast, at the cost of one slow first view per meeting. This warms
them all up front for a demo, and reports how many extracted quotes could be
traced back to a real turn — the number worth watching.
"""

import argparse
import sys

from sqlalchemy import select

from meetingiq.config import get_settings
from meetingiq.db import SessionLocal
from meetingiq.extraction.brief import extract_brief
from meetingiq.llm.registry import get_llm_provider
from meetingiq.models import Meeting
from meetingiq.observability.logging import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract meeting briefs.")
    parser.add_argument("--force", action="store_true", help="Re-extract cached briefs")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    llm = get_llm_provider(settings)

    with SessionLocal() as session:
        meeting_ids = list(session.scalars(select(Meeting.id).order_by(Meeting.meeting_date)))

    if not meeting_ids:
        print("No meetings ingested. Run `make seed` first.", file=sys.stderr)
        return 1

    grounded = total = 0
    for meeting_id in meeting_ids:
        with SessionLocal() as session:
            result = extract_brief(
                session, meeting_id=meeting_id, settings=settings, llm=llm, force=args.force
            )
            meeting = session.get(Meeting, meeting_id)
            grounded += result.grounding.grounded
            total += result.grounding.total
            state = "cached" if result.cached else f"{result.duration_ms / 1000:.0f}s"
            print(
                f"  {meeting.title[:42]:44} "
                f"{result.decision_count}d {result.action_count}a  {state}"
            )
            for quote in result.grounding.ungrounded_quotes:
                print(f"      not in transcript: {quote[:70]}")

    if total:
        print(f"\n{grounded}/{total} extracted quotes traced to a turn ({grounded / total:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
