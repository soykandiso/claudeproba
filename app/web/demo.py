"""Clickable demo of the customer journey, on invented data.

Landing, profile intake, free shortlist and a sample paid report, so the product
can be judged on screen before P2 builds the matching engine behind it. Every
page carries a banner saying the data is invented.

Registered outside production only (app/__init__.py): fake calls with fake
citations must never be publicly reachable. Replace, do not extend, once P2
session 28 renders real match runs.
"""

from datetime import date

from flask import Blueprint, abort, render_template

from app.web import demo_data

bp = Blueprint("demo", __name__, url_prefix="/demo")

_DAYS_IN_WORDS = {
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

VERDICT_LABELS = {
    "eligible": "Можете да аплицирате",
    "likely_eligible": "Веројатно можете да аплицирате",
    "needs_verification": "Потребна е проверка",
    "not_eligible": "Не можете да аплицирате",
}

OUTCOME_LABELS = {
    "satisfied": "Исполнето",
    "not_satisfied": "Треба да се провери",  # a model's not_satisfied never means ineligible
    "unclear": "Нема доволно податоци",
    "attest": "Го потврдувате вие",
}


@bp.app_template_filter("mkdate")
def mkdate(value: date) -> str:
    return value.strftime("%d.%m.%Y")


@bp.app_template_filter("thousands")
def thousands(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


@bp.app_context_processor
def demo_helpers():
    today = date.today()

    def days_left(deadline: date) -> str | None:
        """Words for deadlines under 14 days (design-system: 'says how many days remain')."""
        days = (deadline - today).days
        if days < 0:
            return "рокот помина"
        if days == 0:
            return "рокот истекува денес"
        if days in _DAYS_IN_WORDS:
            return f"уште {_DAYS_IN_WORDS[days]}"
        return None

    return {
        "days_left": days_left,
        "verdict_labels": VERDICT_LABELS,
        "outcome_labels": OUTCOME_LABELS,
        "today": today,
    }


@bp.get("/")
def landing():
    sample = demo_data.find("fitr-novoosnovani")
    return render_template("demo/landing.html", sample=sample.reasons[0])


@bp.get("/profil")
def intake():
    return render_template("demo/intake.html", profile=demo_data.PROFILE)


@bp.route("/lista", methods=["GET", "POST"])
def shortlist():
    # The submitted form is ignored on purpose: the demo always shows one profile.
    calls = demo_data.shortlist()
    return render_template(
        "demo/shortlist.html",
        profile=demo_data.PROFILE,
        open_calls=[c for c in calls if c.verdict != "not_eligible"],
        excluded=[c for c in calls if c.verdict == "not_eligible"],
    )


@bp.get("/izvestaj/<slug>")
def report(slug: str):
    call = demo_data.find(slug)
    if call is None:
        abort(404)
    return render_template("demo/report.html", call=call, profile=demo_data.PROFILE)
