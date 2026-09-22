"""Stage 1 against a real PostgreSQL (roadmap P2 s24).

The acceptance for the row is two claims, and the tests are arranged around them:

1. every operator in the vocabulary is exercised — `tests/test_hard_filter.py` does
   that against the interpreter directly, and `test_every_operator_survives_the_row_round_trip`
   below does it again through `value_json`, which is where a stored criterion can
   drift from what `evaluate()` expects;
2. missing profile data yields `needs_verification`, never `not_eligible` — in the
   SQL of stage 1a (a call must not be filtered away on a blank) as well as in the
   interpreter, which is the half that is easy to remember and the half that is easy
   to forget.
"""

import datetime as dt
import uuid

import psycopg
import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.config import load_settings
from app.matching import stage1
from app.matching.normalise import normalise
from app.matching.operators import Operator, ProfileField
from app.models import (
    Call,
    EligibilityCriterion,
    Programme,
    RawSnapshot,
    ReviewQueueItem,
    SourceFeed,
)
from app.models.enums import AccessMethod, CallStatus, CriterionKind, Verdict
from app.review import extraction as review
from tests.test_pipeline import sessions, site, store  # noqa: F401 -- fixtures
from tests.test_review_extraction import written  # noqa: F401 -- fixture

settings = load_settings()

try:
    with psycopg.connect(settings.database_url, connect_timeout=2):
        DATABASE_AVAILABLE = True
except Exception:
    DATABASE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)

SLUG = "test-stage1"
TODAY = dt.date(2026, 9, 22)
NOW = dt.datetime(2026, 9, 22, 12, 0, tzinfo=dt.UTC)
SOON = dt.datetime(2026, 12, 1, 12, 0, tzinfo=dt.UTC)
# The AV fixture's deadline is in 2026; the pipeline runs it before that date.
AV_NOW = dt.datetime(2026, 8, 10, 12, 0, tzinfo=dt.UTC)

# A Skopje software ДООЕЛ founded in 2022: micro, 62.01, Центар, 44–56 months old.
COMPANY = {
    "entity": "dooel",
    "municipality": "MK00814",
    "founded": "2022",
    "employees": "2-9",
    "nace": "62.01",
    "turnover": "lt10",
    "amount": "1-3",
}


def profile(**overrides):
    answers = {**COMPANY, **overrides}
    return normalise({k: v for k, v in answers.items() if v is not None}, today=TODAY)


@pytest.fixture
def registry():
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    with factory() as s:
        source = s.scalars(select(SourceFeed).where(SourceFeed.slug == SLUG)).first()
        if source is None:
            source = SourceFeed(
                slug=SLUG,
                name_mk="Тест",
                name_en="Test",
                institution="Test",
                base_url="https://gov.example",
                access_method=AccessMethod.HTML,
                expected_cadence=dt.timedelta(days=1),
                staleness_sla=dt.timedelta(days=7),
            )
            s.add(source)
            s.flush()
        # An approved criterion must cite a snapshot: the has_citation check
        # constraint is the accuracy contract in the database (CLAUDE.md).
        snapshot = RawSnapshot(
            source_feed_id=source.id,
            url="https://gov.example/call",
            content_sha256="0" * 64,
            http_status=200,
            storage_key="test/stage1",
            normalised_text="цитат",
        )
        s.add(snapshot)
        # Calls from earlier published sources would join every candidate set.
        s.execute(delete(Call).where(Call.is_published.is_(True)))
        s.commit()
        yield factory, source, snapshot
    transaction.rollback()
    connection.close()
    engine.dispose()


def make_call(session, source, snapshot, *, title="Повик", criteria=(), **columns) -> Call:
    programme = Programme(
        source_feed_id=source.id,
        slug=f"p-{uuid.uuid4()}",
        name_mk=title,
        institution="Test",
        is_singleton=True,
    )
    session.add(programme)
    session.flush()
    call = Call(
        programme_id=programme.id,
        source_feed_id=source.id,
        title_mk=title,
        canonical_url="https://gov.example/call",
        status=columns.pop("status", CallStatus.OPEN),
        deadline_at=columns.pop("deadline_at", SOON),
        is_published=columns.pop("is_published", True),
        **columns,
    )
    session.add(call)
    session.flush()
    for kind, field, operator, value_json in criteria:
        session.add(
            EligibilityCriterion(
                call_id=call.id,
                kind=kind,
                label_mk="Услов",
                field=field,
                operator=operator,
                value_json=value_json,
                source_quote="цитат",
                snapshot_id=snapshot.id,
                quote_start=0,
                quote_end=5,
                is_approved=True,
            )
        )
    session.flush()
    return call


def hard(field, operator, value_json):
    return (CriterionKind.HARD_STRUCTURED, str(field), str(operator), value_json)


# ------------------------------------------------------------------ stage 1a


def test_only_published_open_calls_in_time_are_candidates(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, title="Отворен")
        make_call(s, source, snapshot, title="Неодобрен", is_published=False)
        make_call(s, source, snapshot, title="Затворен", status=CallStatus.CLOSED)
        make_call(
            s, source, snapshot, title="Истечен", deadline_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        )
        make_call(s, source, snapshot, title="Без рок", deadline_at=None)

        found = [c.title_mk for c in stage1.candidates(s, profile(), NOW)]

    assert sorted(found) == ["Без рок", "Отворен"]


def test_an_empty_array_means_no_restriction(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, title="Национален")
        assert len(stage1.candidates(s, profile(), NOW)) == 1


@pytest.mark.parametrize(
    "column,value,kept",
    [
        ("allowed_entity_types", ["micro", "small"], True),
        ("allowed_entity_types", ["farm"], False),
        ("allowed_nace_prefixes", ["62"], True),
        ("allowed_nace_prefixes", ["J"], True),
        ("allowed_nace_prefixes", ["62.01"], True),
        ("allowed_nace_prefixes", ["01", "10"], False),
    ],
)
def test_the_sql_overlaps_on_the_denormalised_columns(registry, column, value, kept):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, **{column: value})
        assert bool(stage1.candidates(s, profile(), NOW)) is kept


@pytest.mark.parametrize("allowed,kept", [(["craftsman"], True), (["sole_trader"], False)])
def test_a_craftsman_reaches_the_sql_as_a_value_the_database_knows(registry, allowed, kept):
    """The profile's types are cast to the column's enum: a value missing from the
    migration would not filter wrongly, it would fail every search a craftsman runs."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, allowed_entity_types=allowed)
        assert bool(stage1.candidates(s, profile(entity="craft"), NOW)) is kept


@pytest.mark.parametrize(
    "bounds,kept",
    [
        ({"min_company_age_months": 24}, True),  # 44–56 is all above
        ({"max_company_age_months": 72}, True),  # all below
        ({"min_company_age_months": 50}, True),  # straddles: 1b answers unclear
        ({"max_company_age_months": 50}, True),  # straddles the other way
        ({"min_company_age_months": 120}, False),  # no month in the range can pass
        ({"max_company_age_months": 12}, False),
    ],
)
def test_an_age_band_is_filtered_permissively_and_judged_conservatively(registry, bounds, kept):
    """Stage 1a may only throw away what 1b would certainly exclude."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, **bounds)
        assert bool(stage1.candidates(s, profile(), NOW)) is kept


@pytest.mark.parametrize(
    "missing,column,value",
    [
        ("nace", "allowed_nace_prefixes", ["01"]),
        ("entity", "allowed_entity_types", ["farm"]),
        ("founded", "min_company_age_months", 120),
        ("municipality", "allowed_regions", ["MK002"]),
    ],
)
def test_a_question_the_profile_does_not_answer_narrows_nothing(registry, missing, column, value):
    """Filtering on a blank is how "we do not know" becomes "you may not apply"."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, **{column: value})
        assert len(stage1.candidates(s, profile(**{missing: None}), NOW)) == 1


def test_a_region_restriction_excludes_an_applicant_from_elsewhere(registry):
    """The column is empty today, but the clause has to be right the day it is filled."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, title="Скопски", allowed_regions=["MK008"])
        make_call(s, source, snapshot, title="Општински", allowed_regions=["MK00814"])
        make_call(s, source, snapshot, title="Источен", allowed_regions=["MK002"])

        found = [c.title_mk for c in stage1.candidates(s, profile(), NOW)]

    assert sorted(found) == ["Општински", "Скопски"]


# ------------------------------------------------------------------ stage 1b


def test_a_call_whose_rules_all_pass_is_eligible(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s,
            source,
            snapshot,
            criteria=[
                hard(ProfileField.ENTITY_TYPE, Operator.IN, {"values": ["micro", "small"]}),
                hard(ProfileField.NACE_CODE, Operator.PREFIX_IN, {"values": ["62"]}),
                hard(ProfileField.AGE_MONTHS, Operator.LTE, {"max": 72}),
            ],
        )
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.verdict == Verdict.ELIGIBLE
    assert [o.verdict for o in outcome.outcomes] == [Verdict.ELIGIBLE] * 3


def test_only_a_rule_can_exclude(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s,
            source,
            snapshot,
            criteria=[hard(ProfileField.ENTITY_TYPE, Operator.NOT_IN, {"values": ["micro"]})],
        )
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.verdict == Verdict.NOT_ELIGIBLE


@pytest.mark.parametrize("missing", ["nace", "founded", "employees", "amount"])
def test_missing_profile_data_is_needs_verification_never_not_eligible(registry, missing):
    """The roadmap's acceptance for this row, one field at a time."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s,
            source,
            snapshot,
            criteria=[
                hard(ProfileField.NACE_CODE, Operator.PREFIX_IN, {"values": ["62"]}),
                hard(ProfileField.AGE_MONTHS, Operator.GTE, {"min": 12}),
                hard(ProfileField.HEADCOUNT, Operator.LTE, {"max": 49}),
                hard(ProfileField.INVESTMENT_SIZE_MKD, Operator.GTE, {"min": 500_000}),
            ],
        )
        [outcome] = stage1.run(s, profile(**{missing: None}), NOW)

    assert outcome.verdict == Verdict.NEEDS_VERIFICATION
    unanswered = [o for o in outcome.outcomes if o.reason_mk == stage1.MISSING]
    assert len(unanswered) == 1


def test_a_band_that_straddles_a_threshold_asks_rather_than_excludes(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s, source, snapshot, criteria=[hard(ProfileField.AGE_MONTHS, Operator.LTE, {"max": 50})]
        )
        [outcome] = stage1.run(s, profile(), NOW)  # 44–56 months

    assert outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert stage1.STRADDLES in outcome.outcomes[0].reason_mk


def test_an_unapproved_criterion_decides_nothing(registry):
    """It is a model's unreviewed opinion; letting it exclude would break invariant 1."""
    factory, source, snapshot = registry
    with factory() as s:
        call = make_call(
            s,
            source,
            snapshot,
            criteria=[hard(ProfileField.ENTITY_TYPE, Operator.NOT_IN, {"values": ["micro"]})],
        )
        for row in s.scalars(
            select(EligibilityCriterion).where(EligibilityCriterion.call_id == call.id)
        ):
            row.is_approved = False
        s.flush()
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.outcomes == []
    assert outcome.verdict == Verdict.NEEDS_VERIFICATION  # nothing checked proves nothing


def test_an_attestation_caps_at_likely_eligible(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s,
            source,
            snapshot,
            criteria=[
                hard(ProfileField.NACE_CODE, Operator.PREFIX_IN, {"values": ["62"]}),
                (CriterionKind.APPLICANT_ATTEST, None, None, None),
            ],
        )
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.verdict == Verdict.LIKELY_ELIGIBLE


@pytest.mark.parametrize("kind", [CriterionKind.NARRATIVE_VERIFY, CriterionKind.DOCUMENTARY])
def test_a_criterion_awaiting_the_verification_pass_is_not_decided(registry, kind):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, criteria=[(kind, None, None, None)])
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert outcome.outcomes[0].reason_mk == stage1.PENDING


# ---------------------------------------------------------- the eligibility gap


def test_a_call_with_unread_conditions_never_reaches_eligible(registry):
    """CLAUDE.md invariant 3 over docs/sources.md §6.6: an EU topic's own text is not all of it."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s,
            source,
            snapshot,
            eligibility_gap="Дел од условите се во документот на повикот.",
            criteria=[hard(ProfileField.NACE_CODE, Operator.PREFIX_IN, {"values": ["62"]})],
        )
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert outcome.capped_by == "Дел од условите се во документот на повикот."


def test_the_gap_does_not_rescue_a_call_the_rules_exclude(registry):
    """An unread document can add a condition, never remove one."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s,
            source,
            snapshot,
            eligibility_gap="Дел од условите се во документот на повикот.",
            criteria=[hard(ProfileField.ENTITY_TYPE, Operator.NOT_IN, {"values": ["micro"]})],
        )
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.verdict == Verdict.NOT_ELIGIBLE
    assert outcome.capped_by is None


# ------------------------------------------------------- the stored predicate


@pytest.mark.parametrize(
    "field,operator,value_json,expected",
    [
        (ProfileField.ENTITY_TYPE, Operator.IN, {"values": ["micro"]}, Verdict.ELIGIBLE),
        (ProfileField.ENTITY_TYPE, Operator.NOT_IN, {"values": ["farm"]}, Verdict.ELIGIBLE),
        (ProfileField.NACE_CODE, Operator.PREFIX_IN, {"values": ["J"]}, Verdict.ELIGIBLE),
        (
            ProfileField.NACE_CODE,
            Operator.PREFIX_NOT_IN,
            {"values": ["62"]},
            Verdict.NOT_ELIGIBLE,
        ),
        (ProfileField.AGE_MONTHS, Operator.GTE, {"min": 12}, Verdict.ELIGIBLE),
        (ProfileField.HEADCOUNT, Operator.LTE, {"max": 49}, Verdict.ELIGIBLE),
        (
            ProfileField.INVESTMENT_SIZE_MKD,
            Operator.BETWEEN,
            {"min": 1_000_000, "max": 3_000_000},
            Verdict.ELIGIBLE,
        ),
    ],
)
def test_every_operator_survives_the_row_round_trip(
    registry, field, operator, value_json, expected
):
    """value_json is where a stored criterion can drift from what evaluate() reads."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, criteria=[hard(field, operator, value_json)])
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.verdict == expected


def test_a_malformed_stored_predicate_asks_rather_than_raising(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s,
            source,
            snapshot,
            criteria=[hard(ProfileField.HEADCOUNT, Operator.BETWEEN, {"min": None})],
        )
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.verdict == Verdict.NEEDS_VERIFICATION


# ------------------------------------------------------------------- ordering


def test_candidates_come_back_by_deadline_soonest_first(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s,
            source,
            snapshot,
            title="Подоцна",
            deadline_at=dt.datetime(2026, 12, 1, tzinfo=dt.UTC),
        )
        make_call(
            s, source, snapshot, title="Прво", deadline_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
        )
        make_call(s, source, snapshot, title="Без рок", deadline_at=None)

        assert [c.title_mk for c in stage1.candidates(s, profile(), NOW)] == [
            "Прво",
            "Подоцна",
            "Без рок",
        ]


# ------------------------------------- end to end, over the real ingestion path


@pytest.mark.usefixtures("store")
def test_an_approved_call_from_the_pipeline_is_matchable(sessions, written):  # noqa: F811
    """Fetch → extract → a human approves → stage 1, with nothing hand-built.

    The point is the seam: `prefilter_columns` fills the denormalised columns at
    approval (app/review/extraction.py) and stage 1a filters on them, so the two
    have to agree about what an empty array means. The AV call's only structured
    criterion is `not_in [municipality]`, which the SQL cannot express — the column
    stays empty, the call is a candidate for everyone, and the interpreter judges it.
    """
    with sessions() as s:
        item = s.get(ReviewQueueItem, written.review_item_id)
        call = s.get(Call, written.call_id)
        assert stage1.candidates(s, profile(), NOW) == []  # not published yet

        review.approve_call(s, item, note="прочитано", now=NOW)
        s.commit()

        assert call.allowed_entity_types == []
        [outcome] = stage1.run(s, profile(), AV_NOW)

    assert outcome.call.id == written.call_id
    structured = [o for o in outcome.outcomes if o.criterion.kind == CriterionKind.HARD_STRUCTURED]
    assert structured and all(o.verdict == Verdict.ELIGIBLE for o in structured)
    # A company is not a municipality, so the rule does not exclude it. What stops
    # this being `eligible` is the attestation the applicant has still to make —
    # exactly the asymmetry the taxonomy exists for.
    assert outcome.verdict == Verdict.LIKELY_ELIGIBLE
    assert {o.criterion.kind for o in outcome.outcomes} >= {
        CriterionKind.HARD_STRUCTURED,
        CriterionKind.APPLICANT_ATTEST,
    }
    assert all(o.reason_mk for o in outcome.outcomes)


def test_a_field_the_vocabulary_no_longer_has_asks_rather_than_raising(registry):
    """Only reachable if operators.py narrows under approved rows — but not with a 500."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, criteria=[hard("turnover_mkd", Operator.GTE, {"min": 1})])
        [outcome] = stage1.run(s, profile(), NOW)

    assert outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert outcome.outcomes[0].reason_mk == stage1.MISSING
