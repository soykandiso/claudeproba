"""Languages (roadmap P3 s40): the switch, the fallback, and how numbers are said.

The acceptance is "locale switch works correctly with only MK content present": asking
for a language that has no catalog gets the Macedonian page, labelled Macedonian. The
switch itself is proven with a two-string English catalog compiled into a temporary
folder, because the repository ships none.
"""

import datetime as dt
import subprocess
import sys

import pytest
from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from flask_babel import force_locale

from app import create_app, i18n
from app.config import load_settings
from app.web import format


def _client():
    return create_app(load_settings(env="testing", version="test")).test_client()


def test_a_language_without_a_catalog_gets_the_macedonian_page_labelled_macedonian():
    """With only Macedonian present, ?lang=sq and an Albanian browser both get Macedonian,
    and <html lang> says so: a page that claims Albanian while showing Macedonian is
    read wrongly by a screen reader. Nothing is remembered for a language that is not
    there."""
    client = _client()
    for response in (
        client.get("/ceni?lang=sq"),
        client.get("/ceni", headers={"Accept-Language": "sq, en;q=0.8"}),
    ):
        body = response.get_data(as_text=True)
        assert '<html lang="mk"' in body and "Детален извештај" in body
        assert "lang=" not in response.headers.get("Set-Cookie", "")


@pytest.fixture
def english(tmp_path, monkeypatch):
    """An English catalog of two strings, where the app looks for catalogs."""
    catalog = Catalog(locale="en")
    catalog.add("Цени", "Prices")
    catalog.add("Детален извештај", "Detailed report")
    folder = tmp_path / "en" / "LC_MESSAGES"
    folder.mkdir(parents=True)
    with (folder / "messages.mo").open("wb") as mo:
        write_mo(mo, catalog)
    monkeypatch.setattr(i18n, "TRANSLATIONS", tmp_path)
    return _client()


def test_a_language_with_a_catalog_is_chosen_remembered_and_left(english):
    body = english.get("/ceni?lang=en").get_data(as_text=True)
    assert '<html lang="en"' in body
    assert "Detailed report" in body and ">Prices</h1>" in body
    # Untranslated strings fall back to the Macedonian they were written in, not a key.
    assert "Листа на повици" in body

    # Remembered by a cookie, so the next page is English without asking again.
    assert '<html lang="en"' in english.get("/ceni").get_data(as_text=True)
    # And left the same way.
    assert '<html lang="mk"' in english.get("/ceni?lang=mk").get_data(as_text=True)
    assert '<html lang="mk"' in english.get("/ceni").get_data(as_text=True)


def test_the_browser_chooses_when_nobody_has(english):
    body = english.get("/ceni", headers={"Accept-Language": "en-GB,en;q=0.9"}).get_data(
        as_text=True
    )
    assert '<html lang="en"' in body


def test_numbers_follow_the_language_and_the_unit_is_the_calls():
    app = create_app(load_settings(env="testing", version="test"))
    with app.test_request_context("/"):
        assert i18n.money(8900) == "8.900 МКД"
        assert i18n.money(145.5, "EUR") == "145,50 EUR" and i18n.money(150, "EUR") == "150 EUR"
        with force_locale("en"):
            assert i18n.number(1234567) == "1,234,567"
        with force_locale("sq"):
            assert i18n.number(8900) == "8\xa0900"
    # Outside a request (the PDF, a CLI) the source language's grouping.
    assert i18n.number(8900) == "8.900"


def test_dates_are_dd_mm_yyyy_whatever_the_language(english):
    """CLAUDE.md: never mm/dd. The date helper takes no locale on purpose."""
    app = create_app(load_settings(env="testing", version="test"))
    with app.test_request_context("/?lang=en"), force_locale("en"):
        assert format.mkdate(dt.date(2026, 11, 30)) == "30.11.2026"


def test_every_marked_string_is_extracted_with_its_plural(tmp_path):
    """What a translator would receive: babel.cfg finds the shell's, the pages' and the
    plurals' strings."""
    pot = tmp_path / "messages.pot"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "babel.messages.frontend",
            "extract",
            "-F",
            "babel.cfg",
            "-o",
            str(pot),
            ".",
        ],
        check=True,
        capture_output=True,
    )
    text = pot.read_text(encoding="utf-8")
    for msgid in ("Оди на содржината", "Детален извештај", "МКД", "Што не правиме"):
        assert f'msgid "{msgid}"' in text, msgid
    assert 'msgid_plural "За првите %(num)d нарачки"' in text
