"""The public archive (roadmap P3 s41–42) under docs/legal-notes.md §3.

Against PostgreSQL in a rolled-back transaction, reusing stage 1's registry fixture: a
test source, a snapshot reading "цитат", no other published call.
"""

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.ai.scrub import mask_contacts
from app.models import EligibilityCriterion, Programme, RawSnapshot
from app.models.enums import CallStatus
from app.web import archive
from tests.test_shortlist import FITS, db, make_call, registry  # noqa: F401 (fixture)


@pytest.fixture
def served(registry, monkeypatch):  # noqa: F811
    factory, source, snapshot = registry
    monkeypatch.setattr("app.web.archive._sessions", lambda: factory)
    monkeypatch.setattr("app.web.shortlist._sessions", lambda: factory)
    return factory, source, snapshot


def _slug(session, call) -> str:
    return session.scalar(select(Programme.slug).where(Programme.id == call.programme_id))


@db
def test_a_published_call_is_in_the_archive_with_its_quoted_conditions(client, served):
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, title="Повик за софтвер", criteria=[FITS])
        s.commit()
        slug = _slug(s, call)

    index = client.get("/arhiva/").get_data(as_text=True)
    assert f"/arhiva/{slug}/" in index and "Повик за софтвер" in index

    programme = client.get(f"/arhiva/{slug}/").get_data(as_text=True)
    assert f"/arhiva/{slug}/{call.id}" in programme

    page = client.get(f"/arhiva/{slug}/{call.id}").get_data(as_text=True)
    assert ">цитат</blockquote>" in page  # the condition's own words, verbatim
    assert "/povici/izvor/" in page and "Последна проверка" in page
    assert call.canonical_url in page  # the whole call is a link, never a copy
    assert '<meta name="robots" content="noindex">' in page  # not production yet


@db
def test_what_the_archive_may_not_show_is_not_there(client, served):
    """Unpublished calls are not in the archive, by list or by address."""
    factory, source, snapshot = served
    with factory() as s:
        hidden = make_call(s, source, snapshot, title="Необјавен", criteria=[FITS])
        hidden.is_published = False
        s.commit()
        slug = _slug(s, hidden)
    assert client.get(f"/arhiva/{slug}/{hidden.id}").status_code == 404
    assert "Необјавен" not in client.get("/arhiva/").get_data(as_text=True)


@db
def test_a_manual_entry_is_left_out(client, served, monkeypatch):
    """A manual entry's text is somebody's copyright (legal-notes §2, §5)."""
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, title="Од донатор", criteria=[FITS])
        s.commit()
        slug = _slug(s, call)
    monkeypatch.setattr(archive, "EXCLUDED_SOURCES", (source.slug,))
    assert client.get(f"/arhiva/{slug}/").status_code == 404
    assert "Од донатор" not in client.get("/arhiva/").get_data(as_text=True)


@db
def test_a_closed_call_stays_and_says_it_is_closed(client, served):
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, title="Лањски повик", criteria=[FITS])
        call.deadline_at = dt.datetime(2025, 3, 31, 21, 59, tzinfo=dt.UTC)
        s.commit()
        slug = _slug(s, call)
    page = client.get(f"/arhiva/{slug}/{call.id}").get_data(as_text=True)
    assert "Затворен." in page and "31.03.2025" in page
    assert "Овој повик е затворен" in page


@db
def test_a_condition_whose_words_moved_is_not_shown_as_one(client, served):
    """Invariant 2: the archive states nothing it cannot cite, and says what it left out."""
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, criteria=[FITS])
        s.execute(
            update(RawSnapshot).where(RawSnapshot.id == snapshot.id).values(normalised_text="друго")
        )
        s.commit()
        slug = _slug(s, call)
    page = client.get(f"/arhiva/{slug}/{call.id}").get_data(as_text=True)
    assert "<blockquote" not in page
    assert "Еден услов не е прикажан" in page


@db
def test_a_cancelled_call_is_not_archived(client, served):
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, criteria=[FITS])
        call.status = CallStatus.CANCELLED
        s.commit()
        slug = _slug(s, call)
    assert client.get(f"/arhiva/{slug}/{call.id}").status_code == 404


def test_the_archive_lets_search_engines_in_only_on_the_real_site():
    templates = Path(archive.__file__).parents[1] / "templates" / "archive"
    for name in ("index.html", "programme.html", "call.html"):
        text = (templates / name).read_text(encoding="utf-8")
        assert "{% block robots %}{{ robots_meta() }}{% endblock %}" in text, name


# ----------------------------------------------- legal-notes rule 7: no persons republished


def test_contacts_are_masked_around_a_quote():
    masked = mask_contacts("Контакт: тел. 02/3123-456, info@skopje.gov.mk, ул. Илинден бр. 82.")
    assert "3123" not in masked and "@" not in masked
    assert "[телефон]" in masked and "[е-пошта]" in masked
    assert "Илинден бр. 82" in masked  # an institution's address is not a person's
    assert mask_contacts("Износ 1 000 000 денари.") == "Износ 1 000 000 денари."


@db
def test_the_passage_masks_a_phone_beside_the_quote_and_never_the_quote(client, served):
    factory, source, snapshot = served
    with factory() as s:
        s.execute(
            update(RawSnapshot)
            .where(RawSnapshot.id == snapshot.id)
            .values(normalised_text="цитат. Контакт: 070 123 456.")
        )
        call = make_call(s, source, snapshot, criteria=[FITS])
        s.commit()
        criterion_id = s.scalar(
            select(EligibilityCriterion.id).where(EligibilityCriterion.call_id == call.id)
        )
    page = client.get(f"/povici/izvor/{criterion_id}").get_data(as_text=True)
    assert '<mark id="quote">цитат</mark>' in page
    assert "070 123 456" not in page and "[телефон]" in page
