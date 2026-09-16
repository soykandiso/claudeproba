"""The demo platform at /demo: the whole customer journey on invented calls.

Built at the demo stage (16.09.2026) so the product can be tried end to end and
the remaining phases prioritised by what the demo shows. Each screen names, on
/demo/vodic, which parts are real code and which phase makes the rest real.

Registered outside production only (app/__init__.py): invented calls with invented
citations must never be publicly reachable. Replace, do not extend, as P2–P6
build the real screens.
"""

from datetime import date

from flask import Blueprint

from app.models.enums import Verdict

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

DECIDED_BY_LABELS = {
    "rule": "проверено според податоците од профилот",
    "model": "проверено според текстот на повикот",
    "applicant": "може да го потврди само фирмата",
}

ORDER_STATE_LABELS = {
    "invoiced": "Издадена профактура",
    "paid": "Уплатено",
    "in_progress": "Во подготовка и преглед",
    "delivered": "Испорачано",
}

SCORE_LABELS = {
    "sector_fit": "Дејност",
    "purpose_fit": "Намена",
    "size_fit": "Износ",
    "timeline_fit": "Рок",
}


def _as_date(value) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


@bp.app_template_filter("mkdate")
def mkdate(value) -> str:
    return _as_date(value).strftime("%d.%m.%Y")


@bp.app_template_filter("thousands")
def thousands(value) -> str:
    return f"{int(value):,}".replace(",", ".")


@bp.app_context_processor
def demo_helpers():
    today = date.today()

    def days_left(deadline) -> str | None:
        """Words for deadlines under 14 days (design-system: 'says how many days remain')."""
        days = (_as_date(deadline) - today).days
        if days < 0:
            return "рокот помина"
        if days == 0:
            return "рокот истекува денес"
        if days in _DAYS_IN_WORDS:
            return f"уште {_DAYS_IN_WORDS[days]}"
        return None

    from app.web.demo import store

    return {
        "days_left": days_left,
        "verdict_labels": VERDICT_LABELS,
        "criterion_labels": CRITERION_LABELS,
        "decided_by_labels": DECIDED_BY_LABELS,
        "order_state_labels": ORDER_STATE_LABELS,
        "score_labels": SCORE_LABELS,
        "today": today,
        "open_reviews": sum(1 for _, still_open in store.review_items() if still_open),
    }


from app.web.demo import admin, customer, orders  # noqa: E402, F401  (register routes)
