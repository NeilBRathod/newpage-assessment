"""Tests for the evaluation runner's decision logic.

The runner decides whether the system declined to answer, and that decision is
what the refusal metric reports. If it is wrong, the number is wrong, so it is
tested directly against real phrasings the model produces.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

from run_eval import ANSWERABLE, GOLDEN_SET, MUST_REFUSE, _declined


def test_an_explicit_refusal_counts():
    assert _declined("anything at all", refused=True)


@pytest.mark.parametrize(
    "answer",
    [
        # All observed from gemma4:12b on the seed corpus.
        'The provided excerpts do not mention a "Frankfurt data centre."',
        "There is no mention of a SOC 2 audit in these transcripts.",
        "The transcripts do not contain information about Q1 churn.",
        "I don't have anything in the meeting transcripts that answers that.",
        "Priya Raman's salary is not discussed in the provided excerpts.",
    ],
)
def test_a_grounded_decline_counts(answer):
    """The soft path is prose, not a flag, so phrasing is what has to be read."""
    assert _declined(answer, refused=False)


@pytest.mark.parametrize(
    "answer",
    [
        "The team reversed the decision on 14 April [2].",
        "Dana benchmarked the ledger and found a p99 of 4.2 seconds [1].",
    ],
)
def test_a_real_answer_does_not_count_as_a_decline(answer):
    assert not _declined(answer, refused=False)


def test_golden_set_parses_and_is_fully_categorised():
    cases = yaml.safe_load(GOLDEN_SET.read_text())["cases"]

    assert len(cases) >= 20
    for case in cases:
        assert case["kind"] in ANSWERABLE | MUST_REFUSE, case["id"]
        assert case["question"].strip()


def test_golden_set_ids_are_unique():
    """Duplicated ids would silently overwrite each other in a report."""
    cases = yaml.safe_load(GOLDEN_SET.read_text())["cases"]

    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))


def test_answerable_cases_name_the_meetings_they_expect():
    cases = yaml.safe_load(GOLDEN_SET.read_text())["cases"]

    for case in cases:
        if case["kind"] in ANSWERABLE:
            assert case.get("expect_meetings"), f"{case['id']} asserts nothing about retrieval"


def test_the_set_covers_both_refusal_mechanisms():
    """They are different mechanisms and can fail independently."""
    kinds = {case["kind"] for case in yaml.safe_load(GOLDEN_SET.read_text())["cases"]}

    assert {"refuse_hard", "refuse_soft", "injection"} <= kinds
