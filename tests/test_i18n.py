"""Languages (roadmap P3 s40): the switch, the fallback, and how numbers are said.

The acceptance is "locale switch works correctly with only MK content present": asking
for a language that has no catalog gets the Macedonian page, labelled Macedonian. The
switch itself is proven with a two-string English catalog compiled into a temporary
folder, because the repository ships none.
"""

import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest
from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from flask_babel import force_locale
from jinja2 import nodes

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


# -- what is marked stays marked (docs/i18n.md, "What is marked") -----------------------

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "web" / "templates"
# The surfaces docs/i18n.md lists as marked. Admin, /stil and /demo are Macedonian by design.
MARKED = [
    "base.html",
    "index.html",
    "pricing.html",
    "_components.html",
    *(f"intake/{p.name}" for p in sorted((TEMPLATES / "intake").glob("*.html"))),
    *(f"shortlist/{p.name}" for p in sorted((TEMPLATES / "shortlist").glob("*.html"))),
]
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
GETTEXT = {"_", "gettext", "ngettext"}


def unmarked(source: str) -> list[str]:
    """Macedonian a translator would never see: text, or a string literal outside _().

    Read from the parsed template rather than with a pattern, so comments are gone and a
    literal is judged by what calls it, not by where it sits on the line.
    """
    tree = jinja2.Environment(extensions=["jinja2.ext.i18n"]).parse(source)
    allowed = {
        id(arg)
        for call in tree.find_all(nodes.Call)
        if isinstance(call.node, nodes.Name) and call.node.name in GETTEXT
        for arg in call.args
    }
    found = [
        node.data.strip()
        for node in tree.find_all(nodes.TemplateData)
        if CYRILLIC.search(node.data)
    ]
    found += [
        node.value
        for node in tree.find_all(nodes.Const)
        if isinstance(node.value, str) and CYRILLIC.search(node.value) and id(node) not in allowed
    ]
    return found


@pytest.mark.parametrize("name", MARKED)
def test_a_marked_surface_has_no_macedonian_outside_gettext(name):
    assert unmarked((TEMPLATES / name).read_text(encoding="utf-8")) == []


def test_the_check_sees_text_and_literals_but_not_comments_or_marked_strings():
    assert unmarked("<p>Цени</p>") == ["<p>Цени</p>"]
    assert unmarked("{{ c.group(rows, header='Цени') }}") == ["Цени"]
    plural = "{{ ngettext('%(num)d ден', '%(num)d дена', n) }}"
    assert unmarked("{# Цени #}{{ _('Цени') }}" + plural) == []


def test_the_intake_and_shortlist_are_translated_when_a_catalog_has_them(tmp_path, monkeypatch):
    """A marked string reaches the page in the page's language, with its numbers."""
    catalog = Catalog(locale="en")
    catalog.add("Профил на фирмата", "Company profile")
    catalog.add("Изберете", "Choose")
    folder = tmp_path / "en" / "LC_MESSAGES"
    folder.mkdir(parents=True)
    with (folder / "messages.mo").open("wb") as mo:
        write_mo(mo, catalog)
    monkeypatch.setattr(i18n, "TRANSLATIONS", tmp_path)
    body = _client().get("/profil/?lang=en").get_data(as_text=True)
    assert "<h1>Company profile</h1>" in body and ">Choose<" in body
    # What the catalog does not have stays the Macedonian it was written in.
    assert "Не е важно за мене" in body
