"""The shortlist (roadmap P2 s28): the service, the page, and the passage behind a quote.

The service runs against PostgreSQL in a rolled-back transaction, reusing stage 1's
registry fixture: the citation check is one SQL query, and it is the thing under test.
"""

import datetime as dt

import pytest
from sqlalchemy import update

from app.matching import shortlist
from app.matching.operators import Operator, ProfileField
from app.models import EligibilityCriterion, RawSnapshot
from app.models.enums import CriterionKind, Verdict
from app.web import format
from tests import test_stage1
from tests.test_stage1 import COMPANY, DATABASE_AVAILABLE, NOW, hard, make_call, profile

# Stage 1's fixture: a test source, a snapshot reading "цитат", no other published call.
registry = test_stage1.registry

db = pytest.mark.skipif(not DATABASE_AVAILABLE, reason="no database reachable")

FITS = hard(ProfileField.NACE_CODE, Operator.PREFIX_IN, {"values": ["62"]})
EXCLUDES = hard(ProfileField.ENTITY_TYPE, Operator.IN, {"values": ["large"]})


def _break_the_quote(session, snapshot):
    session.execute(
        update(RawSnapshot).where(RawSnapshot.id == snapshot.id).values(normalised_text="друго")
    )


# ------------------------------------------------------------------ the service


@db
def test_every_shown_condition_carries_a_citation_found_again(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, criteria=[FITS])
        result = shortlist.build(s, profile(), NOW)

    [entry] = result.open
    [item] = entry.outcome.outcomes
    citation = entry.citation(item)
    assert entry.outcome.verdict == Verdict.ELIGIBLE
    assert (citation.snapshot_id, citation.char_start, citation.char_end) == (snapshot.id, 0, 5)
    assert citation.quote == "цитат" and citation.source_url and citation.retrieved_at


@db
@pytest.mark.parametrize("criteria", [[FITS], [EXCLUDES]])
def test_a_quote_that_is_not_there_any_more_moves_the_call_to_needs_verification(
    registry, criteria
):
    """Invariant 3: an unverifiable citation downgrades — even an exclusion."""
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, criteria=criteria)
        _break_the_quote(s, snapshot)
        result = shortlist.build(s, profile(), NOW)

    [entry] = result.open
    assert entry.outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert entry.outcome.outcomes[0].reason_mk == shortlist.BROKEN_CITATION
    assert entry.citations == {}
    assert result.excluded == []


@db
def test_the_free_depth_is_ten_and_the_total_is_said(registry):
    factory, source, snapshot = registry
    with factory() as s:
        for n in range(12):
            make_call(s, source, snapshot, title=f"Повик {n}")
        result = shortlist.build(s, profile(), NOW)

    assert len(result.open) == shortlist.FREE_DEPTH == 10
    assert result.open_total == 12


@db
def test_an_excluded_call_is_listed_apart_not_dropped(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(s, source, snapshot, title="Отворен")
        make_call(s, source, snapshot, title="Исклучен", criteria=[EXCLUDES])
        result = shortlist.build(s, profile(), NOW)

    assert [e.call.title_mk for e in result.open] == ["Отворен"]
    assert [e.call.title_mk for e in result.excluded] == ["Исклучен"]
    assert result.excluded[0].institution == "Test"


@db
def test_a_preference_is_not_shown_as_a_condition(registry):
    factory, source, snapshot = registry
    with factory() as s:
        make_call(
            s, source, snapshot, criteria=[FITS, (CriterionKind.SOFT_SCORED, None, None, None)]
        )
        [entry] = shortlist.build(s, profile(), NOW).open

    assert entry.outcome.verdict == Verdict.ELIGIBLE
    assert len(entry.outcome.outcomes) == 1 and len(entry.outcome.preferences) == 1


# ------------------------------------------------------------------ the pages


@pytest.fixture
def served(registry, monkeypatch):
    """The page reads through the test's transaction, and the visitor has a profile."""
    factory, source, snapshot = registry
    monkeypatch.setattr("app.web.shortlist._sessions", lambda: factory)
    return factory, source, snapshot


def with_profile(client, **answers):
    with client.session_transaction() as s:
        s["profile"] = {**COMPANY, **answers}


def test_without_a_profile_the_shortlist_sends_you_to_the_form(client):
    response = client.get("/povici/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/profil/")


@db
def test_the_page_shows_the_verdict_the_dates_and_the_way_to_the_words(client, served):
    factory, source, snapshot = served
    deadline = dt.datetime(2026, 12, 1, 12, tzinfo=dt.UTC)
    with factory() as s:
        call = make_call(s, source, snapshot, title="Повик за софтвер", criteria=[FITS])
        call.deadline_at = deadline
        call.grant_max_mkd = 200_000
        s.commit()
        criterion_id = s.query(EligibilityCriterion.id).filter_by(call_id=call.id).scalar()
    with_profile(client)

    body = client.get("/povici/").get_data(as_text=True)

    assert "Повик за софтвер" in body
    assert format.VERDICT_LABELS[Verdict.ELIGIBLE] in body
    assert "01.12.2026" in body and "Последна проверка" in body
    assert "200.000 МКД" in body
    assert f"/povici/izvor/{criterion_id}" in body
    assert "Софтверска" not in body  # nothing but the profile's shape is said back
    for word in ["гарантирано", "guaranteed", "approved", "you will receive"]:
        assert word not in body.lower()


@db
def test_the_passage_page_marks_the_quote_in_the_stored_text(client, served):
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, criteria=[FITS])
        criterion_id = s.query(EligibilityCriterion.id).filter_by(call_id=call.id).scalar()
        s.commit()

    body = client.get(f"/povici/izvor/{criterion_id}").get_data(as_text=True)

    assert '<mark id="quote">цитат</mark>' in body
    assert f"{snapshot.id} 0–5" in body


@db
def test_a_passage_that_cannot_be_shown_is_not_found(client, served):
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, criteria=[FITS])
        criterion_id = s.query(EligibilityCriterion.id).filter_by(call_id=call.id).scalar()
        _break_the_quote(s, snapshot)
        s.commit()

    assert client.get(f"/povici/izvor/{criterion_id}").status_code == 404


@db
def test_an_unapproved_or_unpublished_condition_has_no_public_passage(client, served):
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, criteria=[FITS], is_published=False)
        criterion_id = s.query(EligibilityCriterion.id).filter_by(call_id=call.id).scalar()
        s.commit()

    assert client.get(f"/povici/izvor/{criterion_id}").status_code == 404


# ------------------------------------------------------------------ the words


def test_a_deadline_is_said_in_skopje_time():
    """23:59:59 on the 30th in Skopje is 21:59:59 UTC — still the 30th for the reader."""
    assert format.mkdate(dt.datetime(2026, 6, 30, 21, 59, 59, tzinfo=dt.UTC)) == "30.06.2026"
    assert format.mkdate(dt.datetime(2026, 12, 31, 23, 30, tzinfo=dt.UTC)) == "01.01.2027"


@pytest.mark.parametrize(
    "days,words",
    [(-1, "рокот помина"), (0, "рокот истекува денес"), (9, "уште девет дена"), (14, None)],
)
def test_a_deadline_under_two_weeks_says_the_days_in_words(days, words):
    today = dt.date(2026, 9, 22)
    assert format.days_left(today + dt.timedelta(days=days), today) == words
