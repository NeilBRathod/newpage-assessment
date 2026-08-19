"""Guardrails enforced in code.

A prompt is a request, not a constraint. A 12B model running locally follows
instructions less reliably than a frontier model, so anything that must hold is
checked here rather than hoped for.

Two of these deserve explanation.

**The relevance floor is deliberately low.** Measured against the seed corpus,
top-1 cosine similarity does *not* separate answerable questions from
unanswerable ones — the ranges overlap. "What happened in the August board
meeting?" scores 0.386 (there is genuine talk of board packs and August dates)
while the legitimate "When did we decide to move GA?" scores 0.295. Any
threshold that rejects the first also rejects the second. So the floor does one
job it can do reliably: reject questions with no connection to the corpus at
all, like "what is the capital of France?" (0.069) or a prompt injection
(0.159). Refusing the harder near-misses is the generator's job under a strict
prompt, and it is measured in the eval set rather than asserted here.

**Citation validation cannot prove an answer is grounded**, only that its
citations point at excerpts that were actually supplied. A model can still cite
[2] for a claim [2] does not support. Catching that needs an entailment check,
which is on the "with more time" list.
"""

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from meetingiq.retrieval.hybrid import RetrievedChunk

logger = logging.getLogger(__name__)

# Models group citations as "[2]", "[1, 4]" or "[1,4]" interchangeably, so the
# group is parsed rather than assumed to hold a single number. Matching only
# "[2]" silently under-counts citations and, worse, lets an invalid grouped
# reference through the strip below.
_CITATION = re.compile(r"\[\s*(\d{1,2}(?:\s*,\s*\d{1,2})*)\s*\]")


def _indices(group: str) -> list[int]:
    return [int(part) for part in group.split(",")]


# Phrases a grounded refusal tends to use. Used only to avoid flagging an
# honest "I don't know" as an uncited claim — never to decide whether to refuse.
_REFUSAL_MARKERS = (
    "don't have",
    "do not have",
    "doesn't say",
    "does not say",
    "no mention",
    "not mentioned",
    "not discussed",
    "nothing in the",
    "cannot answer",
    "can't answer",
    "don't cover",
    "do not cover",
)


class RefusalReason(StrEnum):
    NO_RESULTS = "no_results"
    BELOW_RELEVANCE_FLOOR = "below_relevance_floor"
    EMPTY_CORPUS = "empty_corpus"


@dataclass(frozen=True, slots=True)
class RelevanceVerdict:
    should_answer: bool
    reason: RefusalReason | None = None
    top_similarity: float | None = None


def check_relevance(chunks: list[RetrievedChunk], *, minimum_similarity: float) -> RelevanceVerdict:
    """Decide whether to call the generator at all.

    Refusing here saves a slow local generation on a question that has no hope
    of being answered, and makes the refusal deterministic.
    """
    if not chunks:
        return RelevanceVerdict(should_answer=False, reason=RefusalReason.NO_RESULTS)

    similarities = [c.vector_similarity for c in chunks if c.vector_similarity is not None]
    top = max(similarities) if similarities else None

    # No vector hits at all means every candidate came from full-text search,
    # which is a real lexical match — not something to refuse on.
    if top is not None and top < minimum_similarity:
        return RelevanceVerdict(
            should_answer=False,
            reason=RefusalReason.BELOW_RELEVANCE_FLOOR,
            top_similarity=top,
        )
    return RelevanceVerdict(should_answer=True, top_similarity=top)


@dataclass(frozen=True, slots=True)
class CitationAudit:
    cited: list[int]
    invalid: list[int]
    is_grounded: bool
    looks_like_refusal: bool

    @property
    def has_invalid_citations(self) -> bool:
        return bool(self.invalid)


def audit_citations(answer: str, *, excerpt_count: int) -> CitationAudit:
    """Check that every citation points at an excerpt the model was shown.

    A citation outside the supplied range is unambiguously fabricated: the model
    was given excerpts 1..n and nothing else.
    """
    cited = sorted({index for match in _CITATION.findall(answer) for index in _indices(match)})
    invalid = [index for index in cited if index < 1 or index > excerpt_count]
    valid = [index for index in cited if 1 <= index <= excerpt_count]

    lowered = answer.casefold()
    looks_like_refusal = any(marker in lowered for marker in _REFUSAL_MARKERS)

    return CitationAudit(
        cited=cited,
        invalid=invalid,
        # A refusal legitimately has no citations; an assertion should not.
        is_grounded=bool(valid) or looks_like_refusal,
        looks_like_refusal=looks_like_refusal,
    )


def strip_invalid_citations(answer: str, *, excerpt_count: int) -> str:
    """Remove citation markers that point nowhere.

    Leaving them in would show the user a reference they cannot follow, which
    reads as a broken link rather than as the fabrication it is.
    """

    def replace(match: re.Match[str]) -> str:
        valid = [index for index in _indices(match[1]) if 1 <= index <= excerpt_count]
        if not valid:
            return ""
        # Keep the grouping, drop only the references that point nowhere.
        return "[" + ", ".join(str(index) for index in valid) + "]"

    cleaned = _CITATION.sub(replace, answer)
    # Tidy up the double spaces and stranded punctuation removal can leave.
    cleaned = re.sub(r" +([.,;:])", r"\1", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()
