"""Checkout (roadmap P4 s50): order a detailed report, get a proforma within a minute.

A report covers the first five open calls of the customer's shortlist at the moment the
analysis runs (the user's decision of 09.10.2026; app/matching/deep.py). Ordering needs an
account, for the order to belong to someone and the proforma to reach them, and a saved
profile, for the report to be about something.

**The buyer's legal identity is asked here and only here**: the name and address the
proforma is made out to, and the ЕДБ and ЕМБС when the buyer has them. They live on the
order for the invoice alone and never reach a model (invariant 4); the profile stays the
shape of a company, as before.

The proforma is e-mailed as a PDF at once. If the mail fails, the order still stands: the
page says so and offers the PDF, and nothing is lost.
"""

import re
import uuid
from urllib.parse import quote

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from sqlalchemy import select

from app import mail
from app.config import load_settings
from app.db import session_factory
from app.matching.normalise import normalise
from app.models import Account
from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind
from app.orders import proforma, service
from app.pricing import prices
from app.web import account as accounts_web
from app.web import csrf

bp = Blueprint("checkout", __name__, url_prefix="/naracka")
csrf.protect(bp)

_EDB = re.compile(r"^(?:MK|МК)?\d{13}$")
_EMBS = re.compile(r"^\d{7}$")


def _sessions():
    return session_factory(load_settings())


@bp.before_request
def _open_for_orders():
    # The prices say whether reports can be ordered yet (config/prices.yaml).
    if not prices().report.orderable:
        abort(404)


def _signed_in_or_redirect():
    account_id = accounts_web.current_account_id()
    if not account_id:
        return None, redirect(url_for("account.sign_in", next=request.path))
    return account_id, None


def _clean(form) -> tuple[dict, dict]:
    """The buyer's details as typed, and what is wrong with them (field → message)."""
    typed = {key: form.get(key, "").strip() for key in ("name", "address", "edb", "embs")}
    typed["edb"] = typed["edb"].replace(" ", "").upper()
    typed["embs"] = typed["embs"].replace(" ", "")
    errors = {}
    if not typed["name"]:
        errors["name"] = "Внесете го називот на кој се издава профактурата."
    if not typed["address"]:
        errors["address"] = "Внесете ја адресата на купувачот."
    if typed["edb"] and not _EDB.match(typed["edb"]):
        errors["edb"] = "ЕДБ има 13 цифри, со МК напред ако сте обврзник за ДДВ."
    if typed["embs"] and not _EMBS.match(typed["embs"]):
        errors["embs"] = "ЕМБС има 7 цифри."
    return typed, errors


def _form(db, account_id, typed, errors, status=200):
    profile = accounts_web._latest(db, account_id)
    net = service.report_price(db)
    return render_template(
        "checkout/form.html",
        typed=typed,
        errors=errors,
        net=net,
        gross=prices().gross(net),
        founding=net == prices().report.founding.net,
        has_profile=profile is not None,
        profile_summary=_summary(profile),
    ), status


def _summary(profile) -> list[tuple[str, str, None]]:
    if profile is None:
        return []
    from app.matching import intake

    return [
        (label, value or accounts_web.UNKNOWN, None)
        for label, value in intake.describe(normalise(dict(profile.answers)))
    ]


@bp.get("/")
def form():
    account_id, away = _signed_in_or_redirect()
    if away:
        return away
    with _sessions()() as db:
        return _form(db, account_id, {}, {})


@bp.post("/")
def place():
    account_id, away = _signed_in_or_redirect()
    if away:
        return away
    typed, errors = _clean(request.form)
    with _sessions()() as db:
        profile = accounts_web._latest(db, account_id)
        if profile is None:
            return redirect(url_for("intake.form"))
        if errors:
            return _form(db, account_id, typed, errors, 422)
        order, payment = service.create(
            db,
            account_id,
            profile.id,
            service.Buyer(
                typed["name"], typed["address"], typed["edb"] or None, typed["embs"] or None
            ),
        )
        db.commit()
        order_id = order.id
        sent = _mail_proforma(db, order)
    return redirect(url_for("checkout.order", order_id=order_id, sent="1" if sent else "0"))


def _mail_proforma(db, order: Order) -> bool:
    """The proforma to the account's address, as a PDF. False when it could not be sent."""
    invoice = _proforma(db, order.id)
    account = db.get(Account, order.account_id)
    try:
        document = proforma.pdf(invoice, order)
        mail.send(
            current_app.extensions["settings"],
            account.email,
            f"Профактура {invoice.number}",
            render_template("checkout/proforma_mail.txt", invoice=invoice),
            attachments=((f"{invoice.number}.pdf", document, "application/pdf"),),
        )
        return True
    except (mail.MailNotConfigured, proforma.ProformaRefused, OSError):
        current_app.logger.exception("proforma %s not mailed", invoice.number)
        return False


def _proforma(db, order_id) -> Invoice:
    return db.scalar(
        select(Invoice).where(Invoice.order_id == order_id, Invoice.kind == InvoiceKind.PROFORMA)
    )


def _own_order(db, order_id: uuid.UUID, account_id) -> Order:
    order = db.get(Order, order_id)
    if order is None or str(order.account_id) != str(account_id):
        abort(404)  # someone else's order does not exist, as far as this account knows
    return order


@bp.get("/<uuid:order_id>")
def order(order_id: uuid.UUID):
    account_id, away = _signed_in_or_redirect()
    if away:
        return away
    with _sessions()() as db:
        found = _own_order(db, order_id, account_id)
        return render_template(
            "checkout/order.html",
            order=found,
            invoice=_proforma(db, found.id),
            seller=proforma.seller(),
            sent=request.args.get("sent"),
        )


@bp.get("/<uuid:order_id>/profaktura.pdf")
def proforma_pdf(order_id: uuid.UUID):
    account_id, away = _signed_in_or_redirect()
    if away:
        return away
    with _sessions()() as db:
        found = _own_order(db, order_id, account_id)
        invoice = _proforma(db, found.id)
        document = proforma.pdf(invoice, found)
    return current_app.response_class(
        document,
        mimetype="application/pdf",
        # Headers are Latin-1: an ASCII name, and the real one per RFC 5987.
        headers={
            "Content-Disposition": 'inline; filename="profaktura.pdf"; '
            f"filename*=UTF-8''{quote(invoice.number)}.pdf"
        },
    )
