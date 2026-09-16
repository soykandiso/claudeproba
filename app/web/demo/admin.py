"""The operator's side: review queue and source health (P1 s14–15, P2 s33).

No authentication in the demo. The real admin sits behind the operator's own
login (P3 s44) and is never linked from customer pages.
"""

import re

from flask import abort, redirect, render_template, request, url_for
from markupsafe import Markup, escape

from app.reports.lint import find_banned
from app.web.demo import bp, engine, store
from app.web.demo.data import SOURCES
from app.web.demo.orders import delivered_match


@bp.get("/admin")
def admin():
    items = []
    for item_id, still_open in store.review_items():
        kind, key = item_id.split(":")
        if kind == "call":
            call = store.find_call(key)
            items.append(
                {"id": item_id, "kind": "Извлекување на повик", "title": call.title,
                 "flag": call.review_flag, "open": still_open,
                 "url": url_for("demo.admin_call", slug=key)}
            )  # fmt: skip
        else:
            o = store.order(int(key))
            call = store.find_call(o["slug"])
            items.append(
                {"id": item_id, "kind": store.PRODUCTS[o["product"]][0], "title": call.title,
                 "flag": f"Нарачка {o['no']}, профактура {o['invoice']}", "open": still_open,
                 "url": url_for("demo.admin_order", no=o["no"])}
            )  # fmt: skip
    items.sort(key=lambda i: not i["open"])
    return render_template(
        "demo/admin.html",
        items=items,
        reviews={i["id"]: store.review(i["id"]) for i in items},
        sources=SOURCES,
    )


def _in_context(text: str, start: int, end: int, radius: int = 160) -> Markup:
    """The passage around a citation with the quote marked, as stored in the snapshot."""
    a, b = max(0, start - radius), min(len(text), end + radius)
    return Markup("{}{}<mark>{}</mark>{}{}").format(
        "…" if a else "", escape(text[a:start]), text[start:end], escape(text[end:b]),
        "…" if b < len(text) else "",
    )  # fmt: skip


@bp.get("/admin/povik/<slug>")
def admin_call(slug: str):
    call = store.find_call(slug)
    if call is None or call.published:
        abort(404)
    rows = []
    for c in call.criteria:
        cit = call.citation(c)
        context = _in_context(call.document_text, cit.char_start, cit.char_end) if cit else None
        rows.append({"c": c, "citation": cit, "context": context})
    return render_template(
        "demo/admin_call.html",
        call=call,
        rows=rows,
        blocked=any(r["citation"] is None for r in rows),
        review=store.review(f"call:{slug}"),
    )


@bp.post("/admin/povik/<slug>/citat/<key>")
def admin_fix_quote(slug: str, key: str):
    call = store.find_call(slug)
    if call is None or not any(c.key == key and c.corrected_quote for c in call.criteria):
        abort(404)
    store.fix_quote(slug, key)
    return redirect(url_for("demo.admin_call", slug=slug))


@bp.post("/admin/povik/<slug>")
def admin_call_decide(slug: str):
    call = store.find_call(slug)
    if call is None or call.published:
        abort(404)
    action = request.form.get("action")
    if action == "accept":
        if any(call.citation(c) is None for c in call.criteria):
            abort(409)  # no citation, no claim: the button is disabled for this reason
        store.resolve(f"call:{slug}", "accepted")
    elif action == "reject":
        store.resolve(f"call:{slug}", "rejected", request.form.get("note", ""))
    return redirect(url_for("demo.admin"))


def _report_checks(m, order) -> dict:
    body = render_template(
        "demo/_report_body.html", m=m, profile=engine.normalise(order["profile"]), order=order
    )
    text = re.sub(r"<[^>]+>", " ", body)
    citations_ok = all(
        r.citation is not None
        and m.call.document_text[r.citation.char_start : r.citation.char_end] == r.citation.quote
        for r in m.results
    )
    return {"banned": find_banned(text), "citations_ok": citations_ok}


@bp.get("/admin/naracka/<int:no>")
def admin_order(no: int):
    o = store.order(no)
    if o is None or o["state"] not in ("in_progress", "delivered"):
        abort(404)
    m = delivered_match(o)
    rows = [
        {"r": r,
         "context": _in_context(m.call.document_text, r.citation.char_start, r.citation.char_end)
         if r.citation else None}
        for r in m.results
    ]  # fmt: skip
    return render_template(
        "demo/admin_order.html",
        o=o,
        m=m,
        rows=rows,
        profile=engine.normalise(o["profile"]),
        shape=engine.applicant_shape(engine.normalise(o["profile"])),
        checks=_report_checks(m, o),
        review=store.review(f"order:{no}"),
        product_name=store.PRODUCTS[o["product"]][0],
    )


@bp.post("/admin/naracka/<int:no>")
def admin_order_decide(no: int):
    o = store.order(no)
    if o is None or o["state"] != "in_progress":
        abort(404)
    if request.form.get("action") == "accept":
        checks = _report_checks(delivered_match(o), o)
        if checks["banned"] or not checks["citations_ok"]:
            abort(409)
        store.resolve(f"order:{no}", "accepted")
    elif request.form.get("action") == "reject":
        store.resolve(f"order:{no}", "rejected", request.form.get("note", ""))
    return redirect(url_for("demo.admin"))
