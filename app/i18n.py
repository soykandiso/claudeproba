"""Languages (roadmap P3 s40): which one a page is in, and how it says numbers.

**Macedonian is the source.** Every string in the code is the Macedonian a customer
reads, marked with `_()` so a translator can extract it (`babel.cfg`; the workflow
is docs/i18n.md). Macedonian therefore needs no catalog, and a missing translation
shows the Macedonian it was written in, never a key.

**A language is offered only when it exists.** `sq`, `en` and `tr` are the planned
ones (CLAUDE.md), but a locale is chosen only if its compiled catalog is on disk.
Until then `?lang=sq` gets the Macedonian page, and says so: `<html lang>` is the
language the page is actually in, because a screen reader that reads Macedonian
with Albanian rules is worse than no switch at all. Albanian additionally waits
for a named reviewer (docs/decisions.md D7).

**Dates are dd.mm.yyyy in every language** (CLAUDE.md); grouping and decimals follow
the language (8.900 in Macedonian, 8 900 in Albanian, 8,900 in English). The unit
is always МКД or EUR, never a symbol: it is what the calls themselves write.
"""

from decimal import Decimal
from pathlib import Path

from babel.numbers import format_decimal
from flask import Flask, g, has_request_context, request
from flask_babel import Babel, get_locale, gettext

SOURCE = "mk"
PLANNED = ("mk", "sq", "en", "tr")
COOKIE = "lang"
TRANSLATIONS = Path(__file__).resolve().parent / "translations"  # docs/i18n.md


def available(directories: list[Path]) -> tuple[str, ...]:
    """The source, and every planned language with a compiled catalog."""
    found = {
        lang
        for lang in PLANNED
        for directory in directories
        if (directory / lang / "LC_MESSAGES" / "messages.mo").is_file()
    }
    return tuple(lang for lang in PLANNED if lang == SOURCE or lang in found)


def _directories(app: Flask) -> list[Path]:
    return [Path(p) for p in app.config["BABEL_TRANSLATION_DIRECTORIES"].split(";")]


def select_locale() -> str:
    """?lang= first (and remembered), then the cookie, then the browser, then Macedonian."""
    offered = g.get("languages") or (SOURCE,)
    asked = request.args.get("lang")
    if asked in offered:
        g.remember_lang = asked
        return asked
    if request.cookies.get(COOKIE) in offered:
        return request.cookies[COOKIE]
    return request.accept_languages.best_match(offered) or SOURCE


def page_lang() -> str:
    """The language the page is in, for `<html lang>`."""
    return str(get_locale()) if has_request_context() else SOURCE


def number(value, decimals: int = 0) -> str:
    """Grouped as the page's language groups: 8.900, 8 900, 8,900."""
    pattern = "#,##0" + ("." + "0" * decimals if decimals else "")
    return format_decimal(Decimal(str(value)), format=pattern, locale=page_lang())


def money(value, currency: str = "MKD") -> str:
    """An amount and its unit, as the calls write it: «8.900 МКД», «145,50 EUR»."""
    if currency == "EUR":
        decimals = 0 if Decimal(str(value)) == int(value) else 2
        return f"{number(value, decimals)} EUR"
    return f"{number(value)} {gettext('МКД')}"


def init(app: Flask) -> None:
    app.config.setdefault("BABEL_DEFAULT_LOCALE", SOURCE)
    app.config.setdefault("BABEL_TRANSLATION_DIRECTORIES", str(TRANSLATIONS))
    Babel(app, locale_selector=select_locale)

    @app.before_request
    def _offer():
        g.languages = available(_directories(app))

    @app.after_request
    def _remember(response):
        if g.get("remember_lang"):
            response.set_cookie(COOKIE, g.remember_lang, max_age=365 * 24 * 3600, samesite="Lax")
        return response

    app.add_template_global(page_lang, "page_lang")
    app.add_template_filter(number, "number")
    app.add_template_filter(money, "money")
