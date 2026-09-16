"""Stage 1b: the rule interpreter over hard_structured criteria (docs/matching.md §3).

The only module permitted to produce a 'not satisfied' that excludes an applicant
(CLAUDE.md invariant 1). It evaluates one criterion against one normalised
profile and answers satisfied / not_satisfied / unclear; app/matching/taxonomy.py
turns that into the verdict a user sees.

Profile values may be exact or a closed range. Intake asks for bands (employees
2–9, investment 1–3 million МКД) and a founding year rather than a date, so most
numbers are ranges. A range is judged conservatively: satisfied only if every
value in it satisfies the criterion, not satisfied only if none does, and unclear
when it straddles the threshold. Missing data is always unclear (invariant 3).

Built early for the demo stage (16.09.2026) over plain objects; P2 session 24
points it at the call_criterion rows without changing the evaluation.
"""

import enum
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Protocol

from app.matching.operators import FIELDS, NUMBER_OPERATORS, Operator, ProfileField


class RuleResult(enum.StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class Range:
    """Inclusive range of a numeric profile value; lo == hi for an exact value."""

    lo: float
    hi: float

    def __post_init__(self) -> None:
        if self.lo > self.hi:
            raise ValueError(f"empty range {self.lo}..{self.hi}")


class StructuredCriterion(Protocol):
    field: ProfileField
    operator: Operator
    value: object


# The profile as the rules see it: entity_type is a set (a startup is also
# micro), nace_code a string, numeric fields a Range. None or absent = unknown.
Profile = Mapping[ProfileField, object]


# NACE Rev. 2 divisions by section. Fixed by the classification itself, so a
# constant rather than versioned reference data.
_SECTIONS = (
    ("A", 1, 3), ("B", 5, 9), ("C", 10, 33), ("D", 35, 35), ("E", 36, 39), ("F", 41, 43),
    ("G", 45, 47), ("H", 49, 53), ("I", 55, 56), ("J", 58, 63), ("K", 64, 66), ("L", 68, 68),
    ("M", 69, 75), ("N", 77, 82), ("O", 84, 84), ("P", 85, 85), ("Q", 86, 88), ("R", 90, 93),
    ("S", 94, 96), ("T", 97, 98), ("U", 99, 99),
)  # fmt: skip


def nace_section(code: str) -> str | None:
    try:
        division = int(code[:2])
    except ValueError:
        return None
    return next((s for s, lo, hi in _SECTIONS if lo <= division <= hi), None)


def nace_matches(code: str, prefix: str) -> bool:
    """Whether a NACE code falls under a section letter, division, group or class."""
    if prefix.isalpha():
        return nace_section(code) == prefix
    # A division must match whole: "10" covers "10.71" but "1" covers nothing.
    return code == prefix or code.startswith(prefix if "." in prefix else prefix + ".")


def _tri(all_pass: bool, none_pass: bool) -> RuleResult:
    if all_pass:
        return RuleResult.SATISFIED
    if none_pass:
        return RuleResult.NOT_SATISFIED
    return RuleResult.UNCLEAR


def _gte(actual: Range, value: object) -> RuleResult:
    v = float(value)  # type: ignore[arg-type]
    return _tri(actual.lo >= v, actual.hi < v)


def _lte(actual: Range, value: object) -> RuleResult:
    v = float(value)  # type: ignore[arg-type]
    return _tri(actual.hi <= v, actual.lo > v)


def _between(actual: Range, value: object) -> RuleResult:
    lo, hi = (float(x) for x in value)  # type: ignore[union-attr]
    return _tri(lo <= actual.lo and actual.hi <= hi, actual.hi < lo or actual.lo > hi)


def _in(actual: Collection[str], value: object) -> RuleResult:
    return RuleResult.SATISFIED if set(actual) & set(value) else RuleResult.NOT_SATISFIED  # type: ignore[arg-type]


def _not_in(actual: Collection[str], value: object) -> RuleResult:
    return RuleResult.NOT_SATISFIED if set(actual) & set(value) else RuleResult.SATISFIED  # type: ignore[arg-type]


def _prefix_in(actual: str, value: object) -> RuleResult:
    hit = any(nace_matches(actual, p) for p in value)  # type: ignore[union-attr]
    return RuleResult.SATISFIED if hit else RuleResult.NOT_SATISFIED


def _prefix_not_in(actual: str, value: object) -> RuleResult:
    hit = any(nace_matches(actual, p) for p in value)  # type: ignore[union-attr]
    return RuleResult.NOT_SATISFIED if hit else RuleResult.SATISFIED


OPERATORS: dict[Operator, Callable[..., RuleResult]] = {
    Operator.IN: _in,
    Operator.NOT_IN: _not_in,
    Operator.PREFIX_IN: _prefix_in,
    Operator.PREFIX_NOT_IN: _prefix_not_in,
    Operator.GTE: _gte,
    Operator.LTE: _lte,
    Operator.BETWEEN: _between,
}


def evaluate(criterion: StructuredCriterion, profile: Profile) -> RuleResult:
    """One hard_structured criterion against one profile. Never raises on bad data."""
    spec = FIELDS.get(criterion.field)
    if spec is None or criterion.operator not in spec.operators:
        # Extraction refuses these, so reaching here means a bad row: ask, never exclude.
        return RuleResult.UNCLEAR

    actual = profile.get(criterion.field)
    if actual is None or (isinstance(actual, Collection) and not actual):
        return RuleResult.UNCLEAR  # missing data never excludes

    if criterion.operator in NUMBER_OPERATORS:
        if isinstance(actual, int | float):
            actual = Range(actual, actual)
        if not isinstance(actual, Range):
            return RuleResult.UNCLEAR
    try:
        return OPERATORS[criterion.operator](actual, criterion.value)
    except (TypeError, ValueError):
        return RuleResult.UNCLEAR
