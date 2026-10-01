"""Stage 2 (P2 s27): every component, the weights file, and the order.

No database: a Call is built in memory, and stage 1's outcome around it is made by
hand, because what is under test is the arithmetic and the reasons, not the SQL.
"""

import datetime as dt
from pathlib import Path

import pytest
import yaml

from app.matching import stage2
from app.matching.normalise import normalise
from app.matching.stage1 import CallOutcome
from app.models import Call, EligibilityCriterion
from app.models.enums import CriterionKind, Verdict

NOW = dt.datetime(2026, 6, 1, 12, tzinfo=dt.UTC)
TODAY = NOW.date()


def call(**columns) -> Call:
    defaults = {
        "title_mk": "Повик",
        "allowed_nace_prefixes": [],
        "deadline_at": NOW + dt.timedelta(days=60),
    }
    return Call(**{**defaults, **columns})


def profile(**answers):
    return normalise({"entity": "doo", "employees": "2-9", **answers}, today=TODAY)


def outcome(c: Call, verdict=Verdict.NEEDS_VERIFICATION, preferences=()) -> CallOutcome:
    return CallOutcome(c, verdict, [], None, tuple(preferences))


# ------------------------------------------------------------------ components


@pytest.mark.parametrize(
    "prefixes,expected",
    [
        (["10.71"], 1.0),
        (["10.7"], 0.85),
        (["10"], 0.7),
        (["C"], 0.5),
        (["C", "10.71"], 1.0),  # the most specific mention counts
        (["62"], 0.0),
    ],
)
def test_sector_fit_rewards_a_call_that_names_the_activity_specifically(prefixes, expected):
    value, reason = stage2.sector_fit(call(allowed_nace_prefixes=prefixes), profile(nace="10.71"))
    assert value == expected
    assert "10.71" in reason


def test_a_call_open_to_every_activity_is_neutral_not_a_fit():
    assert stage2.sector_fit(call(), profile(nace="10.71"))[0] == stage2.NEUTRAL


def test_an_unanswered_activity_is_neutral_and_says_so():
    value, reason = stage2.sector_fit(call(allowed_nace_prefixes=["10"]), profile())
    assert value == stage2.NEUTRAL
    assert "не е внесена" in reason


@pytest.mark.parametrize(
    "amount,columns,expected",
    [
        ("lt1", {"grant_max_mkd": 200_000}, 1.0),  # 0–1 million reaches down under the cap
        ("1-3", {"grant_max_mkd": 1_000_000}, 1.0),  # touching the cap is inside it
        # 40% of costs up to 200.000 pays its full share of a 500.000 project.
        ("1-3", {"grant_max_mkd": 200_000, "cofinancing_pct": 60}, 0.5),
        ("lt1", {"grant_max_mkd": 200_000, "cofinancing_pct": 60}, 1.0),
        ("gt10", {"grant_max_mkd": 200_000}, 0.5),
    ],
)
def test_a_cap_below_the_investment_is_partial_help_not_a_misfit(amount, columns, expected):
    value, _ = stage2.size_fit(call(**columns), profile(amount=amount))
    assert value == pytest.approx(expected)


def test_a_call_that_states_its_cap_never_ranks_below_one_that_says_nothing():
    """The bakery and the Economy call, as the frozen suite showed them on 22.09.2026."""
    bakery = profile(amount="3-10")
    stated = stage2.size_fit(call(grant_max_mkd=200_000, cofinancing_pct=60), bakery)[0]
    silent = stage2.size_fit(call(), bakery)[0]
    assert stated >= silent


@pytest.mark.parametrize(
    "amount,minimum,expected",
    [("lt1", 1_500_000, 0.5), ("lt1", 2_000_000, 0.0), ("1-3", 1_500_000, 1.0)],
)
def test_below_the_minimum_grant_falls_to_zero_at_half_of_it(amount, minimum, expected):
    value, reason = stage2.size_fit(call(grant_min_mkd=minimum), profile(amount=amount))
    assert value == pytest.approx(expected)
    if expected < 1.0:
        assert "помала" in reason and "МКД" in reason


@pytest.mark.parametrize(
    "columns,answers,word",
    [({}, {"amount": "1-3"}, "повикот не наведува"), ({"grant_max_mkd": 1}, {}, "не сте навеле")],
)
def test_size_fit_is_neutral_when_either_side_is_silent(columns, answers, word):
    value, reason = stage2.size_fit(call(**columns), profile(**answers))
    assert value == stage2.NEUTRAL
    assert word in reason.lower()


@pytest.mark.parametrize(
    "days,expected,phrase",
    [
        (60, 1.0, "остануваат 60 дена"),
        (21, 1.0, "останува 21 ден"),
        # Under 14 days the reason says what the deadline above it says (F17).
        (13, 0.2, "Уште тринаесет дена, кратко"),
        (1, 0.2, "Уште еден ден"),
        (11, 0.2, "Уште единаесет дена"),
        (0, 0.2, "Рокот истекува денес, кратко"),
    ],
)
def test_timeline_fit_penalises_under_two_weeks_and_says_the_days(days, expected, phrase):
    c = call(deadline_at=NOW + dt.timedelta(days=days, hours=1))
    value, reason = stage2.timeline_fit(c, profile(), now=NOW)
    assert value == expected
    assert phrase in reason


def test_a_call_without_a_deadline_is_neutral_on_time():
    assert stage2.timeline_fit(call(deadline_at=None), profile(), now=NOW)[0] == stage2.NEUTRAL


@pytest.mark.parametrize(
    "required,offered,expected",
    [(60, "70", 1.0), (60, "60", 1.0), (60, "30", 0.2), (None, "30", 0.5), (60, None, 0.5)],
)
def test_cofinancing_below_the_requirement_is_fixable_not_zero(required, offered, expected):
    answers = {"cofinancing": offered} if offered else {}
    value, _ = stage2.cofinancing_fit(call(cofinancing_pct=required), profile(**answers))
    assert value == expected


def test_a_preference_is_named_but_scored_neutral_until_the_profile_can_meet_it():
    preference = EligibilityCriterion(kind=CriterionKind.SOFT_SCORED, label_mk="Жени сопственички")
    value, reason = stage2.soft_criteria(call(), profile(), soft=[preference])
    assert value == stage2.NEUTRAL
    assert "Жени сопственички" in reason


def test_every_component_answers_every_profile_with_a_value_and_a_reason():
    """Total: any call and any profile, including an empty one, gives a score."""
    for p in (profile(), normalise({}, today=TODAY), profile(nace="10.71", amount="gt10")):
        for c in (call(), call(deadline_at=None, grant_max_mkd=5, cofinancing_pct=90)):
            scored = stage2.score(outcome(c), p, NOW)
            assert 0.0 <= scored.score <= 1.0
            assert [part.name for part in scored.parts] == list(stage2.COMPONENTS)
            assert all(0.0 <= part.value <= 1.0 and part.reason_mk for part in scored.parts)


# ------------------------------------------------------------------ weights


def test_the_v1_weights_name_every_component_and_sum_to_one():
    weights = stage2.weights("v1")
    assert set(weights) == set(stage2.COMPONENTS)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["semantic_fit"] == 0.0  # not computed yet: it must not move a rank


@pytest.mark.parametrize(
    "body,complaint",
    [
        ({"version": "bad", "weights": {"sector_fit": 1.0}}, "components"),
        (
            {"version": "bad", "weights": {name: 0.1 for name in stage2.COMPONENTS}},
            "sum to",
        ),
        ({"version": "other", "weights": {}}, "says version"),
    ],
)
def test_a_weights_file_that_is_wrong_is_refused(tmp_path, monkeypatch, body, complaint):
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    monkeypatch.setattr(stage2, "WEIGHTS_DIR", Path(tmp_path))
    stage2.weights.cache_clear()
    try:
        with pytest.raises(ValueError, match=complaint):
            stage2.weights("bad")
    finally:
        stage2.weights.cache_clear()


def test_the_score_carries_the_weights_version_that_made_it():
    assert stage2.score(outcome(call()), profile(), NOW).weights_version == "v1"


# ------------------------------------------------------------------ the order


def test_rank_is_by_score_then_by_the_earlier_deadline():
    fits = call(title_mk="Дејност", allowed_nace_prefixes=["10.71"])
    soon = call(title_mk="Порано", deadline_at=NOW + dt.timedelta(days=30))
    late = call(title_mk="Подоцна", deadline_at=NOW + dt.timedelta(days=90))

    ranked = stage2.rank([outcome(late), outcome(soon), outcome(fits)], profile(nace="10.71"), NOW)

    assert [s.call.title_mk for s in ranked] == ["Дејност", "Порано", "Подоцна"]


def test_an_excluded_call_is_ranked_last_however_well_it_scores():
    excluded = call(title_mk="Исклучен", allowed_nace_prefixes=["10.71"])
    plain = call(title_mk="Отворен", deadline_at=NOW + dt.timedelta(days=5))

    ranked = stage2.rank(
        [outcome(excluded, Verdict.NOT_ELIGIBLE), outcome(plain)], profile(nace="10.71"), NOW
    )

    assert [s.call.title_mk for s in ranked] == ["Отворен", "Исклучен"]


def test_ranking_never_changes_a_verdict():
    """Invariant 1 from the other side: stage 2 orders, it does not decide."""
    for verdict in Verdict:
        ranked = stage2.rank([outcome(call(), verdict)], profile(), NOW)
        assert ranked[0].outcome.verdict == verdict
