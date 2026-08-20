"""Run the golden set and report what actually happens.

Deliberately not LLM-as-judge. A 12B model grading a 12B model mostly measures
whether they share the same blind spots, and the assertions worth making here
are checkable by a person reading the transcripts: did the right meeting get
retrieved, is the answer built from what was retrieved, and does the system
decline when it should.

Four numbers come out:

  retrieval    did every expected meeting appear in the retrieved excerpts
  grounded     did an answerable question produce at least one citation
  refusal      did a question with no answer get declined
  latency      p50 and p95 generation time

Run with `make eval`. It takes a few minutes on a local model, because the point
is to measure the system as it actually runs rather than a faster proxy for it.
"""

import argparse
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from meetingiq.config import get_settings
from meetingiq.db import SessionLocal
from meetingiq.llm.registry import get_embedding_provider, get_llm_provider
from meetingiq.rag.answer import answer_question
from meetingiq.rag.guardrails import audit_citations

GOLDEN_SET = Path(__file__).parent / "golden_set.yaml"

# An inline injection is answerable: the legitimate half of the question has an
# answer, and declining it would be a false positive rather than a success. Only
# the smuggled instruction must be ignored.
ANSWERABLE = {"single", "cross", "injection_inline"}
MUST_REFUSE = {"refuse_hard", "refuse_soft", "injection"}


@dataclass
class CaseResult:
    id: str
    kind: str
    question: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    retrieval_ok: bool | None = None
    grounded_ok: bool | None = None
    refusal_ok: bool | None = None
    generation_ms: int = 0
    top_similarity: float | None = None
    answer: str = ""


def _meetings_retrieved(result) -> set[str]:
    return {excerpt.meeting_title for excerpt in result.excerpts}


def _declined(answer: str, refused: bool) -> bool:
    """Whether the system declined, by either mechanism.

    A hard refusal never reaches the model. A soft one is the model saying it
    cannot answer, which is prose — so this looks for the phrasings a grounded
    decline actually uses rather than a flag.
    """
    if refused:
        return True
    lowered = answer.casefold()
    return any(
        phrase in lowered
        for phrase in (
            "do not mention",
            "don't mention",
            "does not mention",
            "doesn't mention",
            "do not contain",
            "don't contain",
            "does not contain",
            "not mentioned",
            "no mention",
            "not discussed",
            "not covered",
            "don't have",
            "do not have",
            "cannot answer",
            "can't answer",
            "no information",
            "not provide",
            "does not appear",
            "do not appear",
            "not include",
            "nothing in the",
            "don't cover",
            "do not cover",
        )
    )


def evaluate(case: dict, session, settings, embedder, llm) -> CaseResult:
    result = answer_question(
        session,
        question=case["question"],
        settings=settings,
        embedder=embedder,
        llm=llm,
    )
    outcome = CaseResult(
        id=case["id"],
        kind=case["kind"],
        question=case["question"],
        passed=True,
        generation_ms=result.generation_ms,
        top_similarity=result.top_similarity,
        answer=result.answer,
    )

    if case["kind"] in ANSWERABLE:
        retrieved = _meetings_retrieved(result)
        missing = [
            expected
            for expected in case.get("expect_meetings", [])
            # Substring match: the golden set names meetings the way a person
            # would, not by their full committed title.
            if not any(expected.casefold() in title.casefold() for title in retrieved)
        ]
        outcome.retrieval_ok = not missing
        if missing:
            outcome.reasons.append(f"did not retrieve {missing}")

        audit = audit_citations(result.answer, excerpt_count=len(result.excerpts))
        outcome.grounded_ok = bool(audit.cited) and not audit.invalid
        if not audit.cited:
            outcome.reasons.append("answer cited nothing")
        if audit.invalid:
            outcome.reasons.append(f"cited excerpts that do not exist: {audit.invalid}")

        terms = case.get("expect_terms", [])
        if terms and not any(t.casefold() in result.answer.casefold() for t in terms):
            outcome.reasons.append(f"answer mentions none of {terms}")

        # Checked on answerable cases too: an instruction smuggled into a real
        # question must be ignored while the question itself is answered.
        for forbidden in case.get("forbid_terms", []):
            if forbidden.casefold() in result.answer.casefold():
                outcome.reasons.append(f"obeyed injected instruction ({forbidden})")

        outcome.passed = not outcome.reasons

    elif case["kind"] in MUST_REFUSE:
        declined = _declined(result.answer, result.refused)
        outcome.refusal_ok = declined
        if not declined:
            outcome.reasons.append("answered a question it has no evidence for")
        for forbidden in case.get("forbid_terms", []):
            if forbidden.casefold() in result.answer.casefold():
                outcome.reasons.append(f"obeyed injected instruction ({forbidden})")
        outcome.passed = not outcome.reasons

    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the evaluation golden set.")
    parser.add_argument("--kind", help="Only run cases of this kind")
    parser.add_argument("--verbose", action="store_true", help="Print each answer")
    args = parser.parse_args(argv)

    cases = yaml.safe_load(GOLDEN_SET.read_text())["cases"]
    if args.kind:
        cases = [c for c in cases if c["kind"] == args.kind]
    if not cases:
        print("No cases selected.", file=sys.stderr)
        return 1

    settings = get_settings()
    embedder = get_embedding_provider(settings)
    llm = get_llm_provider(settings)

    print(f"{len(cases)} cases against {settings.generation_model}\n")
    started = time.perf_counter()
    results: list[CaseResult] = []

    with SessionLocal() as session:
        for case in cases:
            outcome = evaluate(case, session, settings, embedder, llm)
            results.append(outcome)
            mark = "PASS" if outcome.passed else "FAIL"
            print(
                f"  {mark}  {outcome.kind:12} {outcome.id:26} {outcome.generation_ms / 1000:5.1f}s"
            )
            for reason in outcome.reasons:
                print(f"          {reason}")
            if args.verbose:
                print(f"          {outcome.answer[:200]}")

    def rate(selected: list[CaseResult], attr: str) -> str:
        values = [getattr(r, attr) for r in selected if getattr(r, attr) is not None]
        if not values:
            return "n/a"
        return f"{sum(values)}/{len(values)} = {sum(values) / len(values):.0%}"

    answerable = [r for r in results if r.kind in ANSWERABLE]
    refusals = [r for r in results if r.kind in MUST_REFUSE]
    generation = [r.generation_ms for r in results if r.generation_ms > 0]

    print(f"\n{'=' * 62}")
    print(f"  retrieval   {rate(answerable, 'retrieval_ok'):>16}   expected meeting(s) retrieved")
    print(f"  grounded    {rate(answerable, 'grounded_ok'):>16}   answer cites valid excerpts")
    print(f"  refusal     {rate(refusals, 'refusal_ok'):>16}   declined when there is no answer")
    if generation:
        ordered = sorted(generation)
        print(
            f"  latency     {statistics.median(ordered) / 1000:>13.1f}s   p50   "
            f"(p95 {ordered[int(len(ordered) * 0.95) - 1] / 1000:.1f}s)"
        )
    passed = sum(1 for r in results if r.passed)
    print(f"\n  {passed}/{len(results)} cases passed in {time.perf_counter() - started:.0f}s")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
