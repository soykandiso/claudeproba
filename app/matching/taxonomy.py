"""From criterion outcomes to the verdict a user sees (docs/matching.md §7).

The rules and the model report in their own vocabulary: satisfied /
not_satisfied / unclear. This module is the one place that vocabulary becomes a
Verdict, and it encodes the asymmetry the product is built on:

- a rule's not_satisfied is the only route to NOT_ELIGIBLE;
- a model's not_satisfied is NEEDS_VERIFICATION, never NOT_ELIGIBLE;
- anything unclear, from anyone, is NEEDS_VERIFICATION;
- ELIGIBLE needs every criterion satisfied and no attestation outstanding.
"""

import enum
from collections.abc import Iterable
from dataclasses import dataclass

from app.models.enums import Verdict


class DecidedBy(enum.StrEnum):
    RULE = "rule"  # app/matching/hard_filter.py
    MODEL = "model"  # verification pass, citation checked in code
    APPLICANT = "applicant"  # applicant_attest: only the company can confirm it


class Outcome(enum.StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    UNCLEAR = "unclear"
    ATTEST = "attest"  # outstanding until the applicant confirms


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    decided_by: DecidedBy


def criterion_verdict(decision: Decision) -> Verdict:
    if decision.outcome == Outcome.SATISFIED:
        return Verdict.ELIGIBLE
    if decision.outcome == Outcome.ATTEST:
        return Verdict.LIKELY_ELIGIBLE
    if decision.outcome == Outcome.NOT_SATISFIED and decision.decided_by == DecidedBy.RULE:
        return Verdict.NOT_ELIGIBLE
    return Verdict.NEEDS_VERIFICATION


def call_verdict(decisions: Iterable[Decision]) -> Verdict:
    verdicts = [criterion_verdict(d) for d in decisions]
    if not verdicts:
        return Verdict.NEEDS_VERIFICATION  # nothing checked is not evidence of anything
    if Verdict.NOT_ELIGIBLE in verdicts:
        return Verdict.NOT_ELIGIBLE
    if Verdict.NEEDS_VERIFICATION in verdicts:
        return Verdict.NEEDS_VERIFICATION
    if Verdict.LIKELY_ELIGIBLE in verdicts:
        return Verdict.LIKELY_ELIGIBLE
    return Verdict.ELIGIBLE
