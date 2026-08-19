"""`python -m meetingiq.ingest.cli` — ingest transcripts from a directory.

Kept as a module rather than an API endpoint because seeding is an operator
action, not a user one. The upload endpoint in a later phase calls the same
`ingest_transcript`, so there is one ingestion path rather than two that drift.
"""

import argparse
import logging
import sys
from pathlib import Path

from meetingiq.config import get_settings
from meetingiq.db import SessionLocal
from meetingiq.ingest.parser import TranscriptParseError
from meetingiq.ingest.pipeline import ingest_transcript
from meetingiq.llm.registry import get_embedding_provider
from meetingiq.observability.logging import configure_logging

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".txt", ".vtt", ".md"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest meeting transcripts.")
    parser.add_argument("path", type=Path, help="Transcript file or directory")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even when the content hash is unchanged",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)

    if args.path.is_dir():
        files = sorted(p for p in args.path.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)
    else:
        files = [args.path]

    if not files:
        print(f"No transcripts found in {args.path}", file=sys.stderr)
        return 1

    embedder = get_embedding_provider(settings)
    failures = 0

    with SessionLocal() as session:
        for path in files:
            try:
                result = ingest_transcript(
                    session,
                    raw_text=path.read_text(encoding="utf-8"),
                    filename=path.name,
                    settings=settings,
                    embedder=embedder,
                    force=args.force,
                )
            except TranscriptParseError as exc:
                # One bad transcript should not abandon the rest of the batch,
                # but it must be reported rather than silently skipped.
                session.rollback()
                failures += 1
                print(f"  FAILED {path.name}: {exc}", file=sys.stderr)
                continue
            print(f"  {result.summary}")

    if failures:
        print(f"\n{failures} transcript(s) failed to ingest.", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
