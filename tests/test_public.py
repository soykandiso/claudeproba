"""The public surface (roadmap P3 s38–39): the landing page and the prices."""

from pathlib import Path

import pytest

from app.matching import shortlist
from app.pricing import Prices, prices
from app.reports.lint import find_banned
from app.web import public
from tests.test_shortlist import FITS, db, make_call, registry  # noqa: F401 (fixture)


@pytest.fixture
def no_sample(monkeypatch):
    monkeypatch.setattr(public, "_sample", lambda: None)


def test_index_renders(client, no_sample):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.content_type


def test_index_is_macedonian_and_declares_its_language(client, no_sample):
    """lang="mk" is required for correct Macedonian Cyrillic letterforms.

    Without it the browser may pick Russian locale forms, which a native reader
    sees immediately (see .claude/skills/design-system/SKILL.md).
    """
    body = client.get("/").get_data(as_text=True)

    assert 'lang="mk"' in body
    assert "Грантови и субвенции" in body


# ------------------------------------------------------------------ the landing (s38)


def test_the_landing_leads_to_the_free_shortlist_and_says_what_it_is_not(client, no_sample):
    body = client.get("/").get_data(as_text=True)
    assert 'href="/profil/"' in body and 'href="/ceni"' in body
    assert "бесплатна" in body and "не ветување за исходот" in body
    # With no condition that can be shown with its words, no example is invented.
    assert 'id="proof-h"' not in body


def test_the_landing_renders_when_the_database_does_not(client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def down(*_args, **_kwargs):
        raise OperationalError("select", {}, Exception("down"))

    monkeypatch.setattr(shortlist, "sample", down)
    assert client.get("/").status_code == 200


@db
def test_the_landings_example_is_real(client, registry, monkeypatch):  # noqa: F811
    """Invariant 2 on the landing: the quote is found again in the stored text, with its
    source and date, and it links to its passage."""
    factory, source, snapshot = registry
    with factory() as s:
        call = make_call(s, source, snapshot, title="Повик за софтвер", criteria=[FITS])
        s.commit()
    monkeypatch.setattr(shortlist, "SAMPLE_LENGTH", (1, 240))  # the fixture's quote is short
    monkeypatch.setattr(public, "session_factory", lambda _settings: factory)

    body = client.get("/").get_data(as_text=True)

    assert 'id="proof-h"' in body and "„цитат“" not in body  # quotes come from CSS
    assert "<blockquote" in body and ">цитат</blockquote>" in body
    assert "/povici/izvor/" in body and "#quote" in body
    assert call.title_mk in body


# ------------------------------------------------------------------ the prices (s39)


def test_the_prices_are_d1s_and_vat_is_added_once():
    p = prices()
    assert p.report.net == 8900 and p.gross(p.report.net) == 10502
    assert p.report.founding.net == 4900 and p.gross(4900) == 5782
    assert p.gross(p.monitoring.monthly_net) == 1416 and p.gross(p.monitoring.yearly_net) == 14160


def test_the_pricing_page_shows_every_price_without_and_with_vat(client):
    body = client.get("/ceni").get_data(as_text=True)
    for net, gross in (
        ("8.900", "10.502"),
        ("4.900", "5.782"),
        ("1.200", "1.416"),
        ("12.000", "14.160"),
    ):
        assert f"{net} МКД без ДДВ" in body and f"{gross} МКД со ДДВ" in body
    assert "Бесплатно" in body


def test_what_cannot_be_bought_says_so(client):
    """Until P4's order flow and alerts exist, the page offers nothing it cannot sell."""
    body = client.get("/ceni").get_data(as_text=True)
    assert body.count("наскоро") == 1


def test_a_closed_founding_price_is_not_offered(client, monkeypatch):
    p = prices()
    closed = p.model_copy(
        update={
            "report": p.report.model_copy(
                update={"founding": p.report.founding.model_copy(update={"open": False})}
            )
        }
    )
    monkeypatch.setattr(public, "prices", lambda: closed)
    body = client.get("/ceni").get_data(as_text=True)
    assert "4.900" not in body and "првите 10" not in body


def test_a_typo_in_the_price_file_is_an_error(tmp_path):
    bad = tmp_path / "prices.yaml"
    good = (Path(__file__).resolve().parents[1] / "config" / "prices.yaml").read_text(
        encoding="utf-8"
    )
    bad.write_text(good.replace("orderable:", "ordrable:"), encoding="utf-8")
    with pytest.raises(ValueError):
        prices.__wrapped__(bad)
    assert isinstance(prices(), Prices)


def test_neither_page_promises_an_outcome(client, no_sample):
    """The banned-phrase lint (CLAUDE.md) over both pages' own words."""
    for path in ("/", "/ceni"):
        assert find_banned(client.get(path).get_data(as_text=True)) == [], path


def test_prices_are_in_the_navigation_and_marked_there(client):
    body = client.get("/ceni").get_data(as_text=True)
    assert body.count('href="/ceni" aria-current="page"') == 2  # the bar and the tab bar
