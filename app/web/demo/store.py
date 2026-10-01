"""The demo's state, kept in the signed session cookie.

No database, so the demo runs anywhere `flask run` does and each visitor has their
own sandbox. The real rows (applicant_profile, order, invoice, review_queue_item,
subscription) exist in app/models/ and arrive with P2–P6.

The cookie is signed, not encrypted: whoever holds the browser can read it. The
order form says so, and asks for invented company data.
"""

from dataclasses import replace
from datetime import date, datetime

from flask import session

from app.web.demo import data

KEY = "demo"
MAX_ORDERS = 6  # a cookie holds about 4 KB

PRODUCTS = {
    # key: (name, net price МКД) -- decisions.md D1, option B and the package floor
    "report": ("Детален извештај", 8_900),
    "package": ("Пакет документи", 25_000),
}
VAT_RATE = 18

# order states, in the order they happen (app/models/enums.py OrderState)
ORDER_STATES = ("invoiced", "paid", "in_progress", "delivered")


def _state() -> dict:
    return session.setdefault(
        KEY,
        {"profile": None, "orders": [], "reviews": {}, "fixed": [], "sub": None, "seq": {}},
    )


def _save() -> None:
    session.modified = True


def reset() -> None:
    session.pop(KEY, None)


# ---------------------------------------------------------------- profile


def answers() -> dict | None:
    return _state()["profile"]


def save_answers(a: dict) -> None:
    _state()["profile"] = a
    _save()


# ---------------------------------------------------------------- orders


def orders() -> list[dict]:
    return list(reversed(_state()["orders"]))


def order(no: int) -> dict | None:
    return next((o for o in _state()["orders"] if o["no"] == no), None)


def create_order(slug: str, product: str, buyer: dict, profile_answers: dict) -> dict:
    st = _state()
    year = str(date.today().year)
    # Gapless per fiscal year (roadmap P4 s49); the counter never goes backwards.
    st["seq"][year] = st["seq"].get(year, 0) + 1
    net = PRODUCTS[product][1]
    o = {
        "no": max((x["no"] for x in st["orders"]), default=0) + 1,
        "invoice": f"{st['seq'][year]:04d}/{year}",
        "slug": slug,
        "product": product,
        "net": net,
        "vat": net * VAT_RATE // 100,
        "state": "invoiced",
        "created": date.today().isoformat(),
        "paid_ref": None,
        "buyer": buyer,
        # The profile as it was when ordered: the report must be reproducible.
        "profile": profile_answers,
    }
    st["orders"].append(o)
    del st["orders"][:-MAX_ORDERS]
    _save()
    return o


def mark_paid(no: int, bank_ref: str) -> None:
    o = order(no)
    if o and o["state"] == "invoiced":
        o["paid_ref"] = bank_ref
        o["paid_on"] = date.today().isoformat()
        # Payment enqueues the analysis; the result waits for a human (matching.md §6).
        o["state"] = "in_progress"
        _save()


# ---------------------------------------------------------------- review queue


def review(item_id: str) -> dict | None:
    return _state()["reviews"].get(item_id)


def resolve(item_id: str, outcome: str, note: str = "") -> None:
    st = _state()
    st["reviews"][item_id] = {
        "outcome": outcome,  # accepted / rejected
        "note": note[:200],
        "at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
    if outcome == "accepted" and item_id.startswith("order:"):
        o = order(int(item_id.split(":")[1]))
        if o and o["state"] == "in_progress":
            o["state"] = "delivered"
            o["delivered_on"] = date.today().isoformat()
    _save()


def fix_quote(slug: str, key: str) -> None:
    st = _state()
    token = f"{slug}:{key}"
    if token not in st["fixed"]:
        st["fixed"].append(token)
        _save()


def is_fixed(slug: str, key: str) -> bool:
    return f"{slug}:{key}" in _state()["fixed"]


def with_fixes(call: data.DemoCall) -> data.DemoCall:
    """The call as the reviewer left it: corrected quotes replace the model's."""
    criteria = tuple(
        replace(c, quote=c.corrected_quote)
        if c.corrected_quote and is_fixed(call.slug, c.key)
        else c
        for c in call.criteria
    )
    return replace(call, criteria=criteria)


def all_calls() -> list[data.DemoCall]:
    return [with_fixes(c) for c in data.all_calls()]


def find_call(slug: str) -> data.DemoCall | None:
    return next((c for c in all_calls() if c.slug == slug), None)


def published_calls() -> list[data.DemoCall]:
    """Calls a customer may see: published ones, plus any a reviewer accepted."""
    return [
        c
        for c in all_calls()
        if c.published or (review(f"call:{c.slug}") or {}).get("outcome") == "accepted"
    ]


def review_items() -> list[tuple[str, bool]]:
    """(item id, still open) for everything that has passed through the queue."""
    items = []
    for c in data.all_calls():
        if not c.published:
            items.append((f"call:{c.slug}", review(f"call:{c.slug}") is None))
    for o in _state()["orders"]:
        if o["state"] in ("in_progress", "delivered"):
            r = review(f"order:{o['no']}")
            # A rejected report goes back for rework and stays open.
            items.append((f"order:{o['no']}", r is None or r["outcome"] == "rejected"))
    return items


# ---------------------------------------------------------------- monitoring


def subscription() -> dict | None:
    return _state()["sub"]


def subscribe(frequency: str) -> None:
    _state()["sub"] = {"frequency": frequency, "since": date.today().isoformat()}
    _save()


def unsubscribe() -> None:
    _state()["sub"] = None
    _save()
