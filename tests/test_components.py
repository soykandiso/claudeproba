"""The component set (design phase DS3).

`_components.html` is the one place a verdict, a deadline, a cited excerpt, a submit
button, an empty state and an error summary are drawn; `/stil` shows each in each
state. These tests keep the two together and hold the DS1 findings DS3 closed.
What needs eyes (greyscale, the look of a state) is on /stil?siv=1.
"""

import datetime as dt
import re
from pathlib import Path

import pytest
from flask import render_template_string

from app.web import format

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "web" / "templates"
SITE_CSS = re.sub(
    r"/\*.*?\*/",
    "",
    (ROOT / "app" / "web" / "static" / "css" / "site.css").read_text(encoding="utf-8"),
    flags=re.S,
)
COMPONENTS = (TEMPLATES / "_components.html").read_text(encoding="utf-8")

TODAY = dt.date(2026, 10, 1)


def _render(app, source, **context):
    with app.test_request_context("/"):
        return render_template_string(
            '{% import "_components.html" as c with context %}' + source, **context
        )


def _rule(selector: str) -> str:
    """The declarations of the first rule whose selector list contains `selector`."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", SITE_CSS):
        if selector in [s.strip() for s in m.group(1).split(",")]:
            return m.group(2)
    raise AssertionError(f"no rule for {selector}")


def test_every_component_is_on_stil(client):
    macros = re.findall(r"{%-?\s*macro\s+(\w+)\(", COMPONENTS)
    stil = (TEMPLATES / "stil" / "_components.html").read_text(encoding="utf-8")
    assert macros, "no macros found"
    assert [m for m in macros if f"c.{m}(" not in stil] == []
    assert client.get("/stil/").status_code == 200


def test_stil_shows_every_verdict_and_both_colour_modes(client):
    body = client.get("/stil/").get_data(as_text=True)
    for v in ("eligible", "likely_eligible", "needs_verification", "not_eligible"):
        assert f"verdict--{v}" in body
    assert "stil--grey" in client.get("/stil/?siv=1").get_data(as_text=True)


def test_each_verdict_mark_differs_without_colour():
    """F10, redrawn in DL2: each verdict is its own symbol (tokens.css --sym-*), painted
    through a mask in currentColor, so the glyph alone tells it, in greyscale too."""
    tokens = (ROOT / "app" / "web" / "static" / "css" / "tokens.css").read_text(encoding="utf-8")
    symbols = {}
    for verdict, token in [
        ("eligible", "sym-eligible"),
        ("likely_eligible", "sym-likely-eligible"),
        ("needs_verification", "sym-needs-verification"),
        ("not_eligible", "sym-not-eligible"),
    ]:
        assert f"var(--{token})" in _rule(f".verdict--{verdict}")
        symbols[verdict] = re.search(rf"--{token}: (url\([^;]+\));", tokens).group(1)
    assert len(set(symbols.values())) == 4
    # The shapes that carry the meaning: a cut-out disc, a broken ring, a struck ring.
    assert "mask" in symbols["eligible"]
    assert "stroke-dasharray" in symbols["needs_verification"]
    assert "M5.8 10h8.4" in symbols["not_eligible"]
    assert "mask: var(--verdict-symbol)" in _rule(".verdict::before")


@pytest.mark.parametrize(
    ("days", "words", "passed"),
    [
        (30, None, False),
        (9, "уште девет дена", False),
        (0, "рокот истекува денес", False),
        (-3, "рокот помина", True),
    ],
)
def test_deadline_says_the_days_and_drops_the_seal_once_passed(app, days, words, passed):
    html = _render(
        app, "{{ c.deadline(d, today) }}", d=TODAY + dt.timedelta(days=days), today=TODAY
    )
    assert (TODAY + dt.timedelta(days=days)).strftime("%d.%m.%Y") in html
    if words:
        assert words in html
    else:
        assert "," not in html  # a date only, no words after it
    assert ("deadline--passed" in html) is passed


def test_no_deadline_says_so(app):
    assert "Нема краен рок" in _render(app, "{{ c.deadline(none) }}")


def test_the_admin_says_a_deadline_in_the_customers_words(app):
    """F31: one function, so «рокот помина» on both sides."""
    from app.web.admin import _days_left

    passed = dt.datetime(2026, 9, 1, 21, 59, tzinfo=dt.UTC)
    with app.test_request_context("/"):
        assert _days_left(passed) == format.days_left(passed) == "рокот помина"


def test_an_english_quote_is_marked_english(app):
    """F18's component half: a screen reader reads it with the right voice."""
    html = _render(app, "{{ c.excerpt('Applicants must...', source='ec.europa.eu', lang='en') }}")
    assert '<blockquote lang="en">' in html
    assert 'blockquote[lang="en"]' in SITE_CSS


def test_our_own_text_never_wears_the_citation_colour(app):
    """F12: the scrubbed description is ours, not a quote."""
    html = _render(app, "{% call c.excerpt('[ИМЕ] купува машина', own=true) %}x{% endcall %}")
    assert "excerpt--own" in html
    assert "cite-mark" not in html
    assert "--verified" not in _rule(".excerpt--own")
    assert "--verified" not in _rule(".chosen")


def test_a_disabled_submit_says_why_beside_it(app):
    html = _render(
        app, "{{ c.submit('Прифати', disabled_reason='Два цитати недостигаат.', id='ok') }}"
    )
    assert "disabled" in html
    assert 'aria-describedby="ok-why"' in html
    assert 'id="ok-why"' in html and "Два цитати недостигаат." in html


def test_a_submit_says_what_it_is_doing(app):
    html = _render(app, "{{ c.submit('Зачувај', busy='Се зачувува') }}")
    assert 'data-busy="Се зачувува"' in html
    assert "attr(data-busy)" in SITE_CSS
    # submit.js disables the button too; the busy look must win over the disabled one,
    # or the label is paper on paper-sunk (found in DS3's live check).
    assert "var(--tint-strong)" in _rule('.btn[aria-busy="true"]:disabled')


@pytest.mark.parametrize("path", ["/profil/", "/", "/admin/"])
def test_every_shell_loads_the_submit_state(client, path):
    """F25: a pressed button cannot be pressed twice, on the site and in the admin."""
    assert "js/submit.js" in client.get(path).get_data(as_text=True)


def test_the_error_summary_links_each_field(app):
    html = _render(
        app,
        "{{ c.error_summary('Профилот не е зачуван.', items=[('founded', 'Внесете година.')]) }}",
    )
    assert 'role="alert"' in html and 'tabindex="-1"' in html
    assert '<a href="#founded">Внесете година.</a>' in html


def test_expandable_marks_are_drawn_not_typed():
    """F04: no monospace + and − in front of a summary."""
    for selector in ("details.cite > summary::before", "details.why > summary::before"):
        rule = _rule(selector)
        assert "--font-id" not in rule and 'content: ""' in rule


def test_a_checkbox_row_answers_the_pointer():
    """F26."""
    assert "outline" in _rule(".choice:hover input")


# ------------------------------------------------------------- DL2: the new components


def test_glass_is_only_on_the_floating_layer():
    """Apple's HIG and docs/design-language.md: glass for the navigation bar, the tab bar
    and a sheet; never in the content layer. Any other template using it fails here."""
    allowed = {
        "base.html": {"site-header glass glass--bar", "tab-bar glass"},
        "admin/base.html": {"site-header glass glass--bar"},
        "stil/_components.html": {"sheet glass stil-sheet"},
        "stil/index.html": {"stil-backdrop__bar glass"},
    }
    found = {}
    for path in TEMPLATES.rglob("*.html"):
        name = path.relative_to(TEMPLATES).as_posix()
        for cls in re.findall(r'class="([^"]*\bglass\b[^"]*)"', path.read_text(encoding="utf-8")):
            found.setdefault(name, set()).add(cls)
    assert found == allowed


def test_the_customer_shell_has_a_tab_bar_and_the_admin_does_not(client):
    page = client.get("/profil/").get_data(as_text=True)
    assert 'class="tab-bar glass"' in page and 'class="has-tab-bar"' in page
    assert re.search(r'aria-current="page"[^>]*>\s*<svg', page)  # «Профил» is current
    base = (TEMPLATES / "admin" / "base.html").read_text(encoding="utf-8")
    assert "tab-bar" not in base


def test_a_segmented_control_is_a_radio_group_that_posts_without_script(app):
    html = _render(
        app,
        "{{ c.segmented('size', [('micro', 'Микро'), ('small', 'Мало')], 'small', "
        "legend='Големина') }}",
    )
    assert '<fieldset class="segmented"' in html
    assert html.count('type="radio" name="size"') == 2
    assert 'value="small" checked' in html
    assert '<legend class="visually-hidden">Големина</legend>' in html


def test_a_grouped_list_links_a_row_and_says_a_value(app):
    html = _render(
        app,
        "{{ c.group([('Седиште', 'Центар', none), ('Измени', none, '/profil/')], "
        "header='Профил') }}",
    )
    assert '<p class="group__header">Профил</p>' in html
    assert '<span class="group__value">Центар</span>' in html
    assert '<a class="group__row" href="/profil/">' in html
