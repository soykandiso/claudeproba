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

from app.web.format import CRITERION_LABELS, VERDICT_LABELS
from app.web.format import days_left as _days_left

bp = Blueprint("demo", __name__, url_prefix="/demo")

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


@bp.app_context_processor
def demo_helpers():
    today = date.today()

    # This processor is app-wide outside production, so it shadows format.days_left in
    # every template, the components included: it must take the same arguments.
    def days_left(deadline, on: date | None = None) -> str | None:
        return _days_left(deadline, on or today)

    from app.matching import intake
    from app.web.demo import store

    return {
        "days_left": days_left,
        # An answer said back to the applicant, in the words P2 s23 established.
        "form_label": intake.form_label,
        "employees_label": intake.employees_label,
        "amount_label": intake.amount_label,
        "municipality_label": intake.municipality_label,
        "verdict_labels": VERDICT_LABELS,
        "criterion_labels": CRITERION_LABELS,
        "decided_by_labels": DECIDED_BY_LABELS,
        "order_state_labels": ORDER_STATE_LABELS,
        "score_labels": SCORE_LABELS,
        "today": today,
        "open_reviews": sum(1 for _, still_open in store.review_items() if still_open),
    }


from app.web.demo import admin, customer, orders  # noqa: E402, F401  (register routes)
