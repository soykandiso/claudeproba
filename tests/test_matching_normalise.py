"""Stage 0 (docs/matching.md §2, P2 session 22 acceptance).

The table in `tests/fixtures/intake/profiles.yaml` is the acceptance: thirty-odd
intakes, each with the profile fields it must produce. The cases below it are the
properties that no single intake shows.
"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from app.matching.hard_filter import Range, RuleResult, evaluate
from app.matching.normalise import (
    HEADCOUNT_BANDS,
    INVESTMENT_BANDS,
    TURNOVER_BANDS,
    age_months,
    normalise,
    sme_band,
)
from app.matching.operators import FIELDS, Operator, ProfileField
from app.models.enums import EntityType

FIXTURE = yaml.safe_load(
    (Path(__file__).parent / "fixtures" / "intake" / "profiles.yaml").read_text(encoding="utf-8")
)
TODAY = FIXTURE["today"]
CASES = FIXTURE["cases"]


@dataclass(frozen=True)
class Crit:
    field: ProfileField
    operator: Operator
    value: object


def comparable(value: object) -> object:
    """Profile values as the fixture writes them: a Range is [lo, hi], a set is sorted."""
    if isinstance(value, Range):
        return [value.lo, value.hi]
    if isinstance(value, frozenset | set | tuple):
        return sorted(value) if isinstance(value, frozenset | set) else list(value)
    return value


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_intake_normalises(case):
    profile = normalise(case["answers"], today=TODAY)
    actual = {field: comparable(getattr(profile, field)) for field in case["expect"]}
    assert actual == case["expect"]


def test_the_fixture_is_the_acceptance():
    """Thirty intakes, says the roadmap row. Fewer would not be the acceptance."""
    assert len(CASES) >= 30


def test_every_case_is_named_once():
    assert len({c["name"] for c in CASES}) == len(CASES)


# -- properties no single case shows ----------------------------------------------------


def test_normalise_never_raises_on_rubbish():
    """The intake form must be able to post anything at all without a 500."""
    profile = normalise({"entity": None, "nace": [], "founded": [], "employees": {}, "amount": 3})
    assert profile.entity_types == frozenset()
    assert (profile.nace, profile.age_months, profile.headcount) == (None, None, None)
    assert profile.rules_view == {ProfileField.ENTITY_TYPE: frozenset()}


def test_an_answer_that_is_not_a_string_is_still_read():
    """A JSON client that sends a number rather than a string is not wrong."""
    assert normalise({"nace": 62.01}).nace_code == "62.01"


def test_the_profile_carries_no_identity_data():
    """Invariant 4 begins here: what is not collected cannot leak (CLAUDE.md)."""
    profile = normalise({"entity": "dooel", "nace": "62.01"})
    fields = set(vars(profile))
    assert not fields & {"name", "company_name", "embs", "edb", "email", "phone", "address"}


def test_answers_are_kept_verbatim_for_the_form_to_redisplay():
    answers = {"entity": "dooel", "nace": "62.01"}
    assert normalise(answers).answers == answers


@pytest.mark.parametrize("bands", [HEADCOUNT_BANDS, TURNOVER_BANDS, INVESTMENT_BANDS])
def test_bands_are_contiguous_and_ordered(bands):
    """A gap between two bands is an applicant with no answer to give."""
    ranges = [b.values for b in bands.values()]
    assert ranges == sorted(ranges, key=lambda r: r.lo)
    for lower, higher in zip(ranges, ranges[1:], strict=False):
        assert lower.hi in (higher.lo, higher.lo - 1)


def test_age_is_a_range_because_only_the_year_is_asked():
    """Twelve months wide, so a criterion on the boundary asks instead of deciding."""
    got = age_months("2022", dt.date(2026, 9, 22))
    assert got == Range(44, 56)
    over_four_years = Crit(ProfileField.AGE_MONTHS, Operator.GTE, 48)
    assert evaluate(over_four_years, {ProfileField.AGE_MONTHS: got}) == RuleResult.UNCLEAR


def test_age_of_a_company_founded_in_january_is_never_negative():
    assert age_months("2026", dt.date(2026, 1, 15)) == Range(0, 0)


@pytest.mark.parametrize(
    ("headcount", "turnover", "expected"),
    [
        (HEADCOUNT_BANDS["0-1"].values, None, EntityType.MICRO),
        (HEADCOUNT_BANDS["2-9"].values, TURNOVER_BANDS["gt150"].values, EntityType.SMALL),
        (HEADCOUNT_BANDS["10-49"].values, TURNOVER_BANDS["gt150"].values, EntityType.SMALL),
        (HEADCOUNT_BANDS["250+"].values, None, EntityType.LARGE),
        (None, TURNOVER_BANDS["lt10"].values, None),
    ],
)
def test_turnover_can_only_raise_the_size_band(headcount, turnover, expected):
    assert sme_band(headcount, turnover) == expected


def test_rules_view_omits_what_was_not_answered():
    """An absent key is unclear, which asks. A present-but-None key would crash a rule."""
    view = normalise({"entity": "dooel", "employees": "2-9"}).rules_view
    assert set(view) == {ProfileField.ENTITY_TYPE, ProfileField.HEADCOUNT}
    assert all(value is not None for value in view.values())


def test_rules_view_speaks_only_the_vocabulary_the_interpreter_knows():
    profile = normalise(
        {
            "entity": "dooel",
            "nace": "62.01",
            "founded": "2022",
            "employees": "2-9",
            "amount": "1-3",
        },
        today=TODAY,
    )
    assert set(profile.rules_view) <= set(FIELDS)


def test_every_entity_type_the_profile_can_produce_is_a_real_one():
    values = {t.value for t in EntityType}
    for case in CASES:
        assert set(normalise(case["answers"], today=TODAY).entity_types) <= values


def test_an_unresolved_activity_is_unclear_and_never_excludes():
    """Invariant 3: no answer is not a wrong answer (CLAUDE.md)."""
    profile = normalise({"nace": "правиме нешто"})
    criterion = Crit(ProfileField.NACE_CODE, Operator.PREFIX_IN, ["01"])
    assert evaluate(criterion, profile.rules_view) == RuleResult.UNCLEAR


def test_a_call_open_to_a_division_matches_an_applicant_in_one_of_its_classes():
    """What `nace_prefixes` is for: the stage-1a overlap (docs/matching.md §3)."""
    profile = normalise({"nace": "62.01"})
    assert set(profile.nace_prefixes) & {"62"}
