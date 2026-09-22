"""The evaluation harness itself (roadmap P2 s25).

The harness is the thing that will tell the user whether a change to matching made
the product better or worse, so it needs its own tests more than most code: a
scoreboard that is wrong in the reassuring direction is worse than no scoreboard.

Two halves. The first needs no database — the fixtures, the profiles, the case
files and the gate arithmetic. The second loads the frozen registry into
PostgreSQL and asserts that the properties tier A checks actually catch a
violation when there is one; a check that cannot fail proves nothing.

Note what is *not* asserted anywhere here: which verdict any profile gets. That is
the user's judgement, it lives in `evals/cases/`, and the day this file starts
encoding it is the day the harness measures the code against itself.
"""

import copy
import datetime as dt

import psycopg
import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import load_settings
from app.models.enums import CriterionKind, Verdict
from evals import harness

settings = load_settings()

try:
    with psycopg.connect(settings.database_url, connect_timeout=2):
        DATABASE_AVAILABLE = True
except Exception:
    DATABASE_AVAILABLE = False

SUITE = harness.load_suite()
PROFILES = harness.load_profiles()
FIXTURES = harness.load_fixtures()


# ----------------------------------------------------------- what is committed


def test_every_profile_is_answered_the_way_the_form_would_answer_it():
    """A typo in a profile is a silently weaker suite: the field just goes missing."""
    assert len(PROFILES) == 11
    for key, case in PROFILES.items():
        profile = case.profile(SUITE["as_of"])
        assert case.boundary, f"{key}: a profile without a stated boundary is a duplicate"
        assert profile.entity_types or case.answers["entity"] in {"farm", "ngo"}
        assert profile.municipality, f"{key}: municipality {case.answers['municipality']}"
        assert profile.age_months, f"{key}: founded {case.answers.get('founded')}"
        if case.answers.get("nace"):
            assert profile.nace, f"{key}: activity {case.answers['nace']} did not resolve"


def test_every_frozen_quote_is_verbatim_at_the_offsets_it_cites():
    """CLAUDE.md invariant 2, over the fixtures rather than over live documents."""
    for slug, fixture in FIXTURES.items():
        assert fixture.criteria, f"{slug}: a call with no criteria measures nothing"
        for criterion in fixture.criteria:
            found = fixture.text[criterion["quote_start"] : criterion["quote_end"]]
            assert found == criterion["quote"], f"{slug}: {criterion['label_mk']}"


def test_a_frozen_document_still_hashes_as_the_fixture_says():
    """The text and the call.yaml beside it are written together or not at all."""
    import hashlib

    for slug, fixture in FIXTURES.items():
        digest = hashlib.sha256(fixture.text.encode("utf-8")).hexdigest()
        assert digest == fixture.data["document"]["sha256"], f"{slug}: re-run the freeze script"


def test_the_suite_names_only_things_that_exist():
    for slug, roster in SUITE["worksheet"].items():
        assert slug in FIXTURES
        for key in [] if roster == "all" else roster:
            assert key in PROFILES


def test_all_four_applicable_calls_are_open_on_the_suite_date():
    """The clock is chosen so the suite exercises calls, not closed windows."""
    as_of = dt.datetime.combine(SUITE["as_of"], dt.time(12, 0), tzinfo=dt.UTC)
    open_calls = [f for f in FIXTURES.values() if f.shortlistable]
    assert len(open_calls) == 4
    for fixture in open_calls:
        assert fixture.data["deadline_at"] > as_of, fixture.slug


# ------------------------------------------------------------------ case files


def case_file(tmp_path, body: dict) -> None:
    (tmp_path / "case.yaml").write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def cases_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "CASES", tmp_path)
    return tmp_path


def test_a_blank_expected_verdict_is_counted_but_is_not_an_error(cases_dir):
    """The worksheet is filled in over an evening; half of it has to keep working."""
    case_file(
        cases_dir,
        {
            "call": "av-measure-819",
            "cases": [
                {"profile": "p01_skopje_it_micro", "expect": None, "reason": ""},
                {
                    "profile": "p02_bitola_bakery_small",
                    "expect": "likely_eligible",
                    "reason": "Само изјавите остануваат.",
                },
            ],
        },
    )
    cases, problems, unanswered = harness.load_cases(PROFILES, FIXTURES)

    assert problems == []
    assert unanswered == 1
    assert [c.profile for c in cases] == ["p02_bitola_bakery_small"]


@pytest.mark.parametrize(
    "row,complaint",
    [
        ({"profile": "p99_nobody", "expect": "eligible", "reason": "x"}, "no profile"),
        ({"profile": "p01_skopje_it_micro", "expect": "maybe", "reason": "x"}, "not a verdict"),
        ({"profile": "p01_skopje_it_micro", "expect": "eligible", "reason": ""}, "needs a reason"),
    ],
)
def test_a_case_that_measures_nothing_is_reported_not_ignored(cases_dir, row, complaint):
    case_file(cases_dir, {"call": "av-measure-819", "cases": [row]})

    cases, problems, _ = harness.load_cases(PROFILES, FIXTURES)

    assert cases == []
    assert len(problems) == 1 and complaint in problems[0]


def test_the_worksheet_appends_a_new_profile_and_never_rewrites_a_judgement(cases_dir, monkeypatch):
    """A marked case file is a person's evening; a profile added later still needs a row."""
    from evals import run

    monkeypatch.setattr(
        harness, "load_suite", lambda: {**SUITE, "worksheet": {"av-measure-819": "all"}}
    )
    marked = (
        "call: av-measure-819\n"
        "cases:\n"
        "  - profile: p01_skopje_it_micro\n"
        "    expect: likely_eligible\n"
        '    reason: "затоа"\n'
    )
    (cases_dir / "av-measure-819.yaml").write_text(marked, encoding="utf-8")

    run.worksheet()

    text = (cases_dir / "av-measure-819.yaml").read_text(encoding="utf-8")
    assert text.startswith(marked)
    rows = yaml.safe_load(text)["cases"]
    assert [r["profile"] for r in rows] == list(PROFILES)
    assert rows[0]["expect"] == "likely_eligible"
    assert all(r["expect"] is None for r in rows[1:])


def test_a_case_file_for_a_call_that_is_not_frozen_is_an_error(cases_dir):
    case_file(cases_dir, {"call": "fitr-2026-03", "cases": []})

    _, problems, _ = harness.load_cases(PROFILES, FIXTURES)

    assert "no frozen call" in problems[0]


# ------------------------------------------------------------------- the gate


def report(results=(), checks=(), **overrides) -> harness.Report:
    return harness.Report(
        as_of=SUITE["as_of"],
        profiles=len(PROFILES),
        fixtures=len(FIXTURES),
        checks=list(checks),
        results=list(results),
        problems=overrides.pop("problems", []),
        unanswered=overrides.pop("unanswered", 0),
        latency_ms=overrides.pop("latency_ms", [12.0]),
        gate=SUITE["gate"],
    )


def result(expected: str, observed: str) -> harness.Result:
    case = harness.Case("p01_skopje_it_micro", "av-measure-819", expected, "затоа")
    return harness.Result(case, harness.Observed(observed))


def test_an_empty_suite_is_red_because_it_proves_nothing():
    """The state this row ships in, and the reason s26 is the next one."""
    blocked = report().blocking()

    assert blocked == ["no expected verdicts yet: an empty suite proves nothing (P2 s26)"]


def test_one_false_eligible_blocks_however_good_the_rest_is():
    results = [result("likely_eligible", "likely_eligible")] * 99
    results.append(result("not_eligible", "eligible"))

    assert any("false eligible" in reason for reason in report(results).blocking())


@pytest.mark.parametrize("observed", ["not_eligible", harness.NOT_SHOWN])
def test_a_call_that_never_appears_counts_as_an_exclusion(observed):
    """A call missing from the shortlist has no reason beside it: worse, not better."""
    results = [result("eligible", observed)] + [result("eligible", "eligible")] * 39

    assert any("false exclusion" in reason for reason in report(results).blocking())


def test_being_less_certain_than_the_truth_is_reported_but_does_not_block():
    """Today's honest state: the rules ask where a person would know. s27 and s29."""
    results = [result("eligible", "needs_verification")] * 10

    assert report(results).blocking() == []
    assert all(r.under_decided for r in results)


def test_claiming_more_than_the_expected_verdict_warns():
    results = [result("needs_verification", "eligible")]

    assert "claimed more" in " ".join(report(results).warnings())


def test_a_case_that_claimed_more_is_named_not_just_counted():
    """The warning alone does not say where to look; the report has to."""
    results = [result("needs_verification", "likely_eligible")]

    assert "p01_skopje_it_micro × av-measure-819: затоа" in report(results).text()


def test_a_failed_property_blocks_on_its_own():
    check = harness.Check("quotes verbatim", checked=3, failures=["av: not at 10–20"])

    assert report([result("eligible", "eligible")], checks=[check]).blocking() == [
        "quotes verbatim: 1 failure(s)"
    ]


def test_a_slow_stage_one_blocks_and_a_slightly_slow_one_warns():
    slow = report([result("eligible", "eligible")], latency_ms=[9000.0])
    warm = report([result("eligible", "eligible")], latency_ms=[3500.0])

    assert any("latency" in reason for reason in slow.blocking())
    assert slow.blocking() and not warm.blocking()
    assert any("latency" in reason for reason in warm.warnings())


# ------------------------------------------------- the run, over the real SQL

pytestmark_db = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)


@pytest.fixture
def session():
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    with factory() as s:
        yield s
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytestmark_db
def test_tier_a_runs_over_the_frozen_registry_and_every_property_holds(session):
    """The harness runs over the real case files, and since s26 marked them it is green."""
    report = harness.run(session)

    assert [c.name for c in report.checks if not c.ok] == []
    assert all(check.checked for check in report.checks)
    assert report.results
    assert report.blocking() == []


@pytestmark_db
def test_the_citation_check_catches_an_offset_that_has_moved(session):
    """A check that cannot fail is decoration. This is the one the invariant rests on."""
    original = FIXTURES["av-measure-819"]
    data = copy.deepcopy(original.data)
    data["criteria"][0]["quote_start"] += 3
    moved = {"av-measure-819": harness.Fixture("av-measure-819", data, original.text)}

    calls = harness.load_registry(session, moved)
    check = harness._citation_check(session, calls)

    assert not check.ok
    assert "cites" in check.failures[0]


@pytestmark_db
def test_the_registry_is_loaded_the_way_an_approval_would_leave_it(session):
    """The prefilter columns come from the same function /admin calls, not by hand."""
    calls = harness.load_registry(session, FIXTURES)
    economy = calls["economy-call-3"]

    # One `gte 12` on age_months, and a `not_in` that the SQL cannot express.
    assert economy.min_company_age_months == 12
    assert economy.allowed_entity_types == []
    assert economy.is_published is True
    hard = [c for c in FIXTURES["economy-call-3"].criteria if c["kind"] == "hard_structured"]
    assert len(hard) == 2


@pytestmark_db
def test_an_advance_notice_is_in_the_registry_but_never_shortlisted(session):
    """Announced, not open: it has no deadline and nothing to apply to yet."""
    from app.matching import stage1

    report = harness.run(session)
    as_of = dt.datetime.combine(SUITE["as_of"], dt.time(12, 0), tzinfo=dt.UTC)
    for key, case in PROFILES.items():
        found = stage1.run(session, case.profile(SUITE["as_of"]), as_of)
        assert all(o.call.title_mk != FIXTURES["ipard-notice-03-2025"].title for o in found), key
    assert report.fixtures == 5


@pytestmark_db
def test_an_eu_topic_with_an_unread_document_is_capped_for_every_profile(session):
    """Invariant 3 across the whole suite, not one hand-built row (P2 s24)."""
    from app.matching import stage1

    harness.load_registry(session, FIXTURES)
    as_of = dt.datetime.combine(SUITE["as_of"], dt.time(12, 0), tzinfo=dt.UTC)
    gap = FIXTURES["eu-digital-2026-skills-10-edtech"].title

    for key, case in PROFILES.items():
        for outcome in stage1.run(session, case.profile(SUITE["as_of"]), as_of):
            if outcome.call.title_mk == gap:
                assert outcome.verdict != Verdict.ELIGIBLE, key
                assert outcome.verdict != Verdict.LIKELY_ELIGIBLE, key


@pytestmark_db
def test_no_criterion_outside_the_rules_ever_reaches_not_eligible(session):
    """Invariant 1 measured, rather than argued about."""
    report = harness.run(session)
    [check] = [c for c in report.checks if c.name == "only a rule may exclude an applicant"]

    assert check.checked > 0 and check.ok
    kinds = {c["kind"] for f in FIXTURES.values() for c in f.criteria}
    assert kinds > {str(CriterionKind.HARD_STRUCTURED), str(CriterionKind.APPLICANT_ATTEST)}


# ------------------------------------------------------------------ tier B (P2 s29)


@pytest.fixture
def tier_b_world():
    """A session and the factory the gateway writes through, on one rolled-back connection."""
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    with factory() as s:
        yield s, factory
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytestmark_db
def test_tier_b_verifies_every_shown_call_and_every_recorded_answer_passes(tier_b_world):
    """The acceptance of the row: tier B green against the cassettes."""
    session, factory = tier_b_world
    report = harness.run(session, tier="b", session_factory=factory)

    names = {c.name: c for c in report.checks}
    assert names["every recorded answer passed stage 3's gates"].checked > 100
    assert names["every model quote is verbatim at its offsets"].checked > 20
    assert [c.name for c in report.checks if not c.ok] == []
    assert report.blocking() == []


@pytestmark_db
def test_a_paraphrase_in_a_cassette_is_reported_not_believed(tier_b_world, monkeypatch):
    from evals import tier_b

    real = tier_b.load_cassettes()
    craft = "Занаетот е меѓу дефицитарните занаети во изумирање наведени во повикот"
    edited = copy.deepcopy(real)
    answers = edited["skopje-call-12149"][craft]
    # A new dict, not an edit: the cassette's YAML anchor shares one answer
    # between the three filigree makers.
    answers["p07_craftsman_skopje"] = {
        **answers["p07_craftsman_skopje"],
        "quote": "филигранот е меѓу занаетите во изумирање",
    }
    monkeypatch.setattr(tier_b, "load_cassettes", lambda: edited)
    session, factory = tier_b_world

    report = harness.run(session, tier="b", session_factory=factory)

    [failed] = [c for c in report.checks if not c.ok]
    assert failed.name == "every recorded answer passed stage 3's gates"
    assert failed.failures == [
        f"p07_craftsman_skopje × skopje-call-12149: {craft!r} went to review"
    ]
