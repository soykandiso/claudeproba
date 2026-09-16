"""Stage 1 rule interpreter and verdict taxonomy (docs/matching.md §3, §7)."""

from dataclasses import dataclass

import pytest

from app.matching.hard_filter import Range, RuleResult, evaluate, nace_matches, nace_section
from app.matching.operators import Operator, ProfileField
from app.matching.taxonomy import DecidedBy, Decision, Outcome, call_verdict, criterion_verdict
from app.models.enums import Verdict

S, N, U = RuleResult.SATISFIED, RuleResult.NOT_SATISFIED, RuleResult.UNCLEAR


@dataclass(frozen=True)
class Crit:
    field: ProfileField
    operator: Operator
    value: object


@pytest.mark.parametrize(
    ("operator", "value", "actual", "expected"),
    [
        (Operator.GTE, 12, Range(24, 36), S),
        (Operator.GTE, 12, Range(0, 6), N),
        (Operator.GTE, 12, Range(6, 18), U),  # straddles: ask, never exclude
        (Operator.LTE, 72, Range(24, 36), S),
        (Operator.LTE, 72, Range(80, 90), N),
        (Operator.LTE, 72, 72, S),  # exact numbers are a one-point range
        (Operator.BETWEEN, [1, 49], Range(2, 9), S),
        (Operator.BETWEEN, [1, 49], Range(50, 249), N),
        (Operator.BETWEEN, [1, 49], Range(10, 60), U),
    ],
)
def test_number_operators_judge_ranges_conservatively(operator, value, actual, expected):
    assert (
        evaluate(Crit(ProfileField.HEADCOUNT, operator, value), {ProfileField.HEADCOUNT: actual})
        == expected
    )


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        (Operator.IN, ["micro", "small"], S),
        (Operator.IN, ["farm"], N),
        (Operator.NOT_IN, ["farm", "large"], S),
        (Operator.NOT_IN, ["micro"], N),
    ],
)
def test_entity_type_overlap(operator, value, expected):
    profile = {ProfileField.ENTITY_TYPE: {"micro", "startup"}}
    assert evaluate(Crit(ProfileField.ENTITY_TYPE, operator, value), profile) == expected


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        (Operator.PREFIX_IN, ["62"], S),
        (Operator.PREFIX_IN, ["J"], S),
        (Operator.PREFIX_IN, ["62.0"], S),
        (Operator.PREFIX_IN, ["C", "01"], N),
        (Operator.PREFIX_NOT_IN, ["47", "56"], S),
        (Operator.PREFIX_NOT_IN, ["62.01"], N),
    ],
)
def test_nace_prefixes(operator, value, expected):
    profile = {ProfileField.NACE_CODE: "62.01"}
    assert evaluate(Crit(ProfileField.NACE_CODE, operator, value), profile) == expected


def test_nace_hierarchy_does_not_match_across_divisions():
    assert not nace_matches("10.71", "1")
    assert not nace_matches("62.01", "6")
    assert nace_section("01.13") == "A"
    assert nace_section("xx") is None


@pytest.mark.parametrize("profile", [{}, {ProfileField.HEADCOUNT: None}])
def test_missing_profile_data_is_unclear_never_not_satisfied(profile):
    assert evaluate(Crit(ProfileField.HEADCOUNT, Operator.LTE, 49), profile) == U


def test_operator_outside_the_vocabulary_is_unclear():
    crit = Crit(ProfileField.NACE_CODE, Operator.GTE, 5)
    assert evaluate(crit, {ProfileField.NACE_CODE: "62.01"}) == U


def test_malformed_value_is_unclear_not_an_exception():
    crit = Crit(ProfileField.HEADCOUNT, Operator.BETWEEN, "not a pair")
    assert evaluate(crit, {ProfileField.HEADCOUNT: Range(1, 2)}) == U


def test_only_a_rule_can_make_a_call_not_eligible():
    assert (
        criterion_verdict(Decision(Outcome.NOT_SATISFIED, DecidedBy.RULE)) == Verdict.NOT_ELIGIBLE
    )
    assert (
        criterion_verdict(Decision(Outcome.NOT_SATISFIED, DecidedBy.MODEL))
        == Verdict.NEEDS_VERIFICATION
    )


@pytest.mark.parametrize(
    ("decisions", "expected"),
    [
        ([], Verdict.NEEDS_VERIFICATION),
        (
            [(Outcome.SATISFIED, DecidedBy.RULE), (Outcome.SATISFIED, DecidedBy.MODEL)],
            Verdict.ELIGIBLE,
        ),
        (
            [(Outcome.SATISFIED, DecidedBy.RULE), (Outcome.ATTEST, DecidedBy.APPLICANT)],
            Verdict.LIKELY_ELIGIBLE,
        ),
        (
            [(Outcome.ATTEST, DecidedBy.APPLICANT), (Outcome.UNCLEAR, DecidedBy.RULE)],
            Verdict.NEEDS_VERIFICATION,
        ),
        (
            [(Outcome.SATISFIED, DecidedBy.RULE), (Outcome.NOT_SATISFIED, DecidedBy.MODEL)],
            Verdict.NEEDS_VERIFICATION,
        ),
        (
            [(Outcome.NOT_SATISFIED, DecidedBy.RULE), (Outcome.SATISFIED, DecidedBy.MODEL)],
            Verdict.NOT_ELIGIBLE,
        ),
    ],
)
def test_call_verdict(decisions, expected):
    assert call_verdict(Decision(o, d) for o, d in decisions) == expected
