"""Ordering, the proforma invoice, simulated payment, and what gets delivered (P4, P5)."""

import re

from flask import abort, redirect, render_template, request, url_for

from app.matching.normalise import normalise
from app.web.demo import bp, engine, store
from app.web.demo.data import PURPOSES

_EMBS = re.compile(r"^\d{7}$")
_EDB = re.compile(r"^(?:MK|МК)?\d{13}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Invented, and visibly so. The real seller is decisions.md D4.
SELLER = {
    "name": "Демо Консалтинг ДООЕЛ Скопје",
    "edb": "MK0000000000000",
    "embs": "0000000",
    "account": "000-0000000000-00",
    "bank": "Демо банка АД Скопје",
}


def _call_or_404(slug: str):
    call = next((c for c in store.published_calls() if c.slug == slug), None)
    if call is None:
        abort(404)
    return call


def _order_or_404(no: int) -> dict:
    o = store.order(no)
    if o is None:
        abort(404)
    return o


@bp.route("/naracka/<slug>/<product>", methods=["GET", "POST"])
def order_form(slug: str, product: str):
    call = _call_or_404(slug)
    if product not in store.PRODUCTS:
        abort(404)
    if store.answers() is None:
        return redirect(url_for("demo.intake"))

    buyer = {"name": "", "embs": "", "edb": "", "city": "", "email": ""}
    errors: dict[str, str] = {}
    if request.method == "POST":
        buyer = {k: request.form.get(k, "").strip()[:120] for k in buyer}
        buyer["edb"] = buyer["edb"].replace(" ", "").upper()
        if len(buyer["name"]) < 3:
            errors["name"] = "Внесете го називот како што е во Централниот регистар."
        if not _EMBS.match(buyer["embs"]):
            errors["embs"] = "ЕМБС има 7 цифри."
        if not _EDB.match(buyer["edb"]):
            errors["edb"] = "ЕДБ има 13 цифри, со или без MK на почетокот."
        if not buyer["city"]:
            errors["city"] = "Внесете го местото на седиштето."
        if not _EMAIL.match(buyer["email"]):
            errors["email"] = "Внесете е-пошта на која ќе стигне профактурата."
        if not errors:
            o = store.create_order(slug, product, buyer, store.answers())
            return redirect(url_for("demo.order_detail", no=o["no"]))

    name, net = store.PRODUCTS[product]
    return render_template(
        "demo/order_form.html",
        call=call,
        product=product,
        product_name=name,
        net=net,
        vat=net * store.VAT_RATE // 100,
        buyer=buyer,
        errors=errors,
    ), (422 if errors else 200)


@bp.get("/naracki/<int:no>")
def order_detail(no: int):
    o = _order_or_404(no)
    return render_template(
        "demo/order.html",
        o=o,
        call=store.find_call(o["slug"]),
        product_name=store.PRODUCTS[o["product"]][0],
        seller=SELLER,
        states=store.ORDER_STATES,
        review=store.review(f"order:{no}"),
    )


@bp.post("/naracki/<int:no>/uplata")
def order_pay(no: int):
    _order_or_404(no)
    ref = request.form.get("bank_ref", "").strip()[:40] or "ДЕМО-УПЛАТА"
    store.mark_paid(no, ref)
    return redirect(url_for("demo.order_detail", no=no))


def delivered_match(o: dict):
    """The match as it was for the profile saved with the order, not the current one."""
    call = store.find_call(o["slug"])
    return engine.match(call, normalise(o["profile"]))


@bp.get("/naracki/<int:no>/izvestaj")
def order_report(no: int):
    o = _order_or_404(no)
    if o["state"] != "delivered" or o["product"] != "report":
        abort(404)
    m = delivered_match(o)
    return render_template(
        "demo/report.html", m=m, profile=normalise(o["profile"]), order=o,
        review=store.review(f"order:{no}"), sample_profile=False,
    )  # fmt: skip


@bp.get("/naracki/<int:no>/paket")
def order_package(no: int):
    o = _order_or_404(no)
    if o["state"] != "delivered" or o["product"] != "package":
        abort(404)
    m = delivered_match(o)
    return render_template(
        "demo/package.html",
        m=m,
        o=o,
        profile=normalise(o["profile"]),
        review=store.review(f"order:{no}"),
        purpose_words=", ".join(PURPOSES[p] for p in o["profile"].get("inv", [])),
    )
