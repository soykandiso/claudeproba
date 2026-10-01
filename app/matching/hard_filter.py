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
import math
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Protocol

from app.matching.operators import FIELDS, LIST_OPERATORS, NUMBER_OPERATORS, Operator, ProfileField


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


@dataclass(frozen=True)
class Prefilter:
    """The denormalised hard-filter columns on `call` (docs/matching.md §3, stage 1a)."""

    allowed_entity_types: list[str]
    allowed_nace_prefixes: list[str]
    allowed_regions: list[str]
    min_company_age_months: int | None
    max_company_age_months: int | None


def prefilter_columns(criteria: Collection[StructuredCriterion]) -> Prefilter:
    """What stage 1a's SQL may exclude on, from a call's approved hard_structured criteria.

    The SQL runs before the interpreter above and throws rows away, so it must never
    exclude a profile the interpreter would keep or call unclear. It is a coarse
    superset, and the interpreter stays the judge:

    - one `in` on entity_type becomes allowed_entity_types; the SQL overlap test is
      exactly `_in`. Two of them are a conjunction the overlap cannot express
      (a startup that is also micro satisfies `in [startup]` and `in [micro]`), so
      they, and every `not_in`, leave the column empty.
    - one `prefix_in` on nace_code becomes allowed_nace_prefixes, for the same reason.
    - numeric bounds on age_months are a true conjunction: the largest minimum and
      the smallest maximum, rounded outward so no boundary profile is lost.
    - regions have no profile field yet (app/matching/operators.py), so no restriction.

    Filled when a human approves the call (app/review/extraction.py), never from
    unapproved extraction.
    """
    by_field: dict[ProfileField, list[StructuredCriterion]] = {}
    for criterion in criteria:
        by_field.setdefault(ProfileField(criterion.field), []).append(criterion)

    def single_list(field: ProfileField, operator: Operator) -> list[str]:
        found = by_field.get(field, [])
        if len(found) == 1 and found[0].operator == operator:
            return sorted(str(v) for v in found[0].value)  # type: ignore[union-attr]
        return []

    minimums, maximums = [], []
    for criterion in by_field.get(ProfileField.AGE_MONTHS, []):
        value = criterion.value
        if criterion.operator == Operator.GTE:
            minimums.append(float(value))  # type: ignore[arg-type]
        elif criterion.operator == Operator.LTE:
            maximums.append(float(value))  # type: ignore[arg-type]
        elif criterion.operator == Operator.BETWEEN:
            low, high = (float(x) for x in value)  # type: ignore[union-attr]
            minimums.append(low)
            maximums.append(high)

    return Prefilter(
        allowed_entity_types=single_list(ProfileField.ENTITY_TYPE, Operator.IN),
        allowed_nace_prefixes=single_list(ProfileField.NACE_CODE, Operator.PREFIX_IN),
        allowed_regions=[],
        min_company_age_months=math.floor(max(minimums)) if minimums else None,
        max_company_age_months=math.ceil(min(maximums)) if maximums else None,
    )


@dataclass(frozen=True)
class Stored:
    """A stored criterion's predicate in the shape evaluate() reads.

    eligibility_criterion.value_json is {"values": [...]} for list operators and
    {"min": x, "max": y} for numbers (app/ai/schemas.py ExtractedCriterion.value_json).
    """

    field: ProfileField
    operator: Operator
    value: object

    @classmethod
    def from_row(cls, field: str, operator: str, value_json: Mapping | None) -> "Stored":
        op = Operator(operator)
        data = value_json or {}
        if op in LIST_OPERATORS:
            value: object = list(data.get("values") or [])
        elif op == Operator.GTE:
            value = data.get("min")
        elif op == Operator.LTE:
            value = data.get("max")
        else:
            value = (data.get("min"), data.get("max"))
        return cls(ProfileField(field), op, value)
