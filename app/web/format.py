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

# Design system: a deadline under 14 days also says how many days remain, in words.
DAYS_IN_WORDS = {
    1: "еден ден",
    2: "два дена",
    3: "три дена",
    4: "четири дена",
    5: "пет дена",
    6: "шест дена",
    7: "седум дена",
    8: "осум дена",
    9: "девет дена",
    10: "десет дена",
    11: "единаесет дена",
    12: "дванаесет дена",
    13: "тринаесет дена",
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


def thousands(value) -> str:
    """12.000, as Macedonian writes it."""
    return f"{int(value):,}".replace(",", ".")


def days_left(deadline, today: dt.date | None = None) -> str | None:
    """Words for a deadline under 14 days away, or None when the date alone will do."""
    days = (_as_date(deadline) - (today or dt.date.today())).days
    if days < 0:
        return "рокот помина"
    if days == 0:
        return "рокот истекува денес"
    if days in DAYS_IN_WORDS:
        return f"уште {DAYS_IN_WORDS[days]}"
    return None


def deadline_passed(deadline, today: dt.date | None = None) -> bool:
    """A passed deadline stops wearing --seal: the seal means a clock is running."""
    return _as_date(deadline) < (today or dt.date.today())


def register(app: Flask) -> None:
    app.add_template_filter(mkdate, "mkdate")
    app.add_template_filter(thousands, "thousands")
    app.add_template_global(days_left, "days_left")
    app.add_template_global(deadline_passed, "deadline_passed")
    app.add_template_global(VERDICT_LABELS, "verdict_labels")
    app.add_template_global(CRITERION_LABELS, "criterion_labels")
