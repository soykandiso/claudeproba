"""How the site says dates, amounts, deadlines and verdicts — once, for every screen.

These started in the demo (16.09.2026). The shortlist (P2 s28) is the first real
screen that needs them, and the demo is not registered in production, so they
live here and the demo imports them. The words are the ones the user approved in
the demo; a verdict is said the same way on every page or it stops meaning one thing.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from flask import Flask

from app.models.enums import Verdict
from app.wording import days_in_words

VERDICT_LABELS = {
    Verdict.ELIGIBLE: "Можете да аплицирате",
    Verdict.LIKELY_ELIGIBLE: "Веројатно можете да аплицирате",
    Verdict.NEEDS_VERIFICATION: "Потребна е проверка",
    Verdict.NOT_ELIGIBLE: "Не можете да аплицирате",
}

# Per criterion, after taxonomy: a model's not_satisfied already reads as "check".
CRITERION_LABELS = {
    Verdict.ELIGIBLE: "Исполнето",
    Verdict.LIKELY_ELIGIBLE: "Го потврдувате вие",
    Verdict.NEEDS_VERIFICATION: "Треба да се провери",
    Verdict.NOT_ELIGIBLE: "Не е исполнето",
}

# Deadlines are said in Skopje's calendar: 23:59 on the 30th is still the 30th.
SKOPJE = ZoneInfo("Europe/Skopje")


def _as_date(value) -> dt.date:
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    if isinstance(value, dt.datetime):
        return (value.astimezone(SKOPJE) if value.tzinfo else value).date()
    return value


def mkdate(value) -> str:
    """dd.mm.yyyy, the only date format a person reads here (CLAUDE.md)."""
    return _as_date(value).strftime("%d.%m.%Y")


def instant(value: str | None) -> dt.datetime | None:
    """A stored ISO instant (a report draft keeps deadlines so) as a datetime."""
    return dt.datetime.fromisoformat(value) if value else None


def thousands(value) -> str:
    """12.000, as Macedonian writes it."""
    return f"{int(value):,}".replace(",", ".")


def days_left(deadline, today: dt.date | None = None) -> str | None:
    """Words for a deadline under 14 days away, or None when the date alone will do."""
    # The words are app/wording.py's, shared with stage 2's reasons (F17).
    return days_in_words((_as_date(deadline) - (today or dt.date.today())).days)


def deadline_passed(deadline, today: dt.date | None = None) -> bool:
    """A passed deadline stops wearing --seal: the seal means a clock is running."""
    return _as_date(deadline) < (today or dt.date.today())


# (one, many) for each condition verdict, most consequential first.
_COUNTED = (
    (Verdict.NOT_ELIGIBLE, "не е исполнет", "не се исполнети"),
    (Verdict.NEEDS_VERIFICATION, "треба да се провери", "треба да се проверат"),
    (Verdict.LIKELY_ELIGIBLE, "го потврдувате вие", "ги потврдувате вие"),
    (Verdict.ELIGIBLE, "е исполнет", "се исполнети"),
)


def condition_counts(verdicts) -> str | None:
    """Why a call has its verdict, in one line (DS5): how its conditions came out.

    «Од 5 услови: 1 треба да се провери, 4 ги потврдувате вие.» Counts only, of the
    conditions listed under it, each of which carries its quote; it adds no claim of
    its own. Most consequential first, so the reason for the verdict leads.
    """
    verdicts = list(verdicts)
    if not verdicts:
        return None
    parts = []
    for verdict, one, many in _COUNTED:
        n = sum(1 for v in verdicts if v == verdict)
        if n:
            parts.append(f"{n} {one if n == 1 else many}")
    noun = "услов" if len(verdicts) == 1 else "услови"
    return f"Од {len(verdicts)} {noun}: {', '.join(parts)}."


def lang_of(text: str | None) -> str:
    """The language of an institution's words, for `lang` on a quote or a title (F18).

    Nothing stores it: a snapshot has no language column, and an EU call is English
    while an Economy call can quote its Albanian half. So it is read off the letters,
    which is enough for the three languages a call here is written in: mostly
    Cyrillic is Macedonian; Latin with ë or ç is Albanian (standard Albanian can hardly
    write a sentence without ë); other Latin is English. It only chooses a voice and
    quotation marks, never what anything means, so a wrong guess costs a mispronounced
    passage, not a verdict.
    """
    if not text:
        return "mk"
    cyrillic = sum("Ѐ" <= ch <= "ӿ" for ch in text)
    latin = sum(ch.isascii() and ch.isalpha() for ch in text)
    if cyrillic >= latin:
        return "mk"
    return "sq" if any(ch in "ëËçÇ" for ch in text) else "en"


def register(app: Flask) -> None:
    app.add_template_filter(mkdate, "mkdate")
    app.add_template_filter(thousands, "thousands")
    app.add_template_filter(instant, "instant")
    app.add_template_filter(lang_of, "lang_of")
    app.add_template_global(condition_counts, "condition_counts")
    app.add_template_global(days_left, "days_left")
    app.add_template_global(deadline_passed, "deadline_passed")
    app.add_template_global(VERDICT_LABELS, "verdict_labels")
    app.add_template_global(CRITERION_LABELS, "criterion_labels")
