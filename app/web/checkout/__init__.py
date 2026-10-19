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
from app.ingestion.snapshots import SnapshotStore
from app.matching.normalise import from_row as normalise_row
from app.matching.normalise import normalise
from app.models import Account
from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind, OrderState
from app.orders import deliver, numbering, proforma, service
from app.pricing import prices
from app.web import account as accounts_web
from app.web import csrf

bp = Blueprint("checkout", __name__, url_prefix="/naracka")
csrf.protect(bp)

_EDB = re.compile(r"^(?:MK|МК)?\d{13}$")
_EMBS = re.compile(r"^\d{7}$")


def _sessions():
    return session_factory(load_settings())


PACKAGE_ENDPOINTS = {"checkout.package_form", "checkout.place_package"}
REPORT_ENDPOINTS = {"checkout.form", "checkout.place"}


@bp.before_request
def _open_for_orders():
    # The prices say what can be ordered yet (config/prices.yaml): each product by its own
    # switch, and the order pages while either is on.
    p = prices()
    if request.endpoint in PACKAGE_ENDPOINTS:
        allowed = p.package.orderable
    elif request.endpoint in REPORT_ENDPOINTS:
        allowed = p.report.orderable
    else:
        allowed = p.report.orderable or p.package.orderable
    if not allowed:
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


def open_calls(db, profile) -> int:
    """How many calls the report would cover if the analysis ran now: the shortlist's open
    calls the rules do not exclude, at most five (`deep.run` takes the same ones)."""
    from app.matching import deep, shortlist

    now = numbering.now()
    scored, _ = shortlist.ranked(db, normalise_row(profile, now.date()), now)
    return min(sum(1 for s in scored if not s.excluded), deep.DEPTH)


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
        calls=open_calls(db, profile) if profile is not None else 0,
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
        if open_calls(db, profile) == 0:
            # Nothing to analyse: a report of no calls is not sold (the form says so too).
            return _form(db, account_id, typed, {}, 409)
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


# ------------------------------------------------------------------ a document package (P5 s75)


def _package_call(db, call_id):
    """The call and its package, or 404: published, open, with exactly one package."""
    from app.documents import packages
    from app.models import Call, SourceFeed

    call = db.get(Call, call_id)
    if call is None or not call.is_published:
        abort(404)
    if call.deadline_at is not None and call.deadline_at <= numbering.now():
        abort(404)  # a package for a call that has closed is not sold
    source = db.get(SourceFeed, call.source_feed_id)
    package = packages.for_call(source.slug, call.title_mk)
    if package is None:
        abort(404)
    return call, package


def _package_page(db, account_id, call, package, typed, errors, status=200):
    from app.documents import TEMPLATES, checklist

    net = prices().package.net
    titles = [checklist.manifest_for(TEMPLATES / d).title_mk for d in package.documents]
    included = [*titles, "Што уште треба да подготвите"]  # the checklist comes last
    profile = accounts_web._latest(db, account_id)
    return render_template(
        "checkout/package_form.html",
        call=call,
        package=package,
        included=included,
        net=net,
        gross=prices().gross(net),
        typed=typed,
        errors=errors,
        has_profile=profile is not None,
    ), status


@bp.get("/paket/<uuid:call_id>")
def package_form(call_id: uuid.UUID):
    account_id, away = _signed_in_or_redirect()
    if away:
        return away
    with _sessions()() as db:
        call, package = _package_call(db, call_id)
        return _package_page(db, account_id, call, package, {}, {})


@bp.post("/paket/<uuid:call_id>")
def place_package(call_id: uuid.UUID):
    account_id, away = _signed_in_or_redirect()
    if away:
        return away
    typed, errors = _clean(request.form)
    with _sessions()() as db:
        call, package = _package_call(db, call_id)
        profile = accounts_web._latest(db, account_id)
        if profile is None:
            return redirect(url_for("intake.form"))
        if errors:
            return _package_page(db, account_id, call, package, typed, errors, 422)
        order, _ = service.create_package(
            db,
            account_id,
            profile.id,
            call.id,
            service.Buyer(
                typed["name"], typed["address"], typed["edb"] or None, typed["embs"] or None
            ),
        )
        db.commit()
        order_id = order.id
        sent = _mail_proforma(db, order)
    return redirect(url_for("checkout.order", order_id=order_id, sent="1" if sent else "0"))


def _what(db, order: Order) -> dict:
    """What the order is for, as its pages and mails say it: a report, or a call's package."""
    from app.models import Call
    from app.models.documents import DocumentPackage

    if service.sku_of(db, order) != service.PACKAGE:
        return {"is_package": False, "call_title": None}
    package = db.scalar(select(DocumentPackage).where(DocumentPackage.order_id == order.id))
    call = db.get(Call, package.call_id) if package else None
    return {"is_package": True, "call_title": call.title_mk if call else None}


def _mail_proforma(db, order: Order) -> bool:
    """The proforma to the account's address, as a PDF. False when it could not be sent."""
    invoice = _proforma(db, order.id)
    account = db.get(Account, order.account_id)
    try:
        document = proforma.pdf(invoice, order, description=proforma.describe(db, order))
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


def mail_paid(db, order_id) -> bool:
    """Tell the buyer the payment arrived and what happens next (P4 s52). False if not sent."""
    order = db.get(Order, order_id)
    if service.sku_of(db, order) in (service.MONTH, service.YEAR):
        return True  # a subscription's activation e-mail says it, with the period and invoice
    invoice = _proforma(db, order.id)
    account = db.get(Account, order.account_id)
    try:
        mail.send(
            current_app.extensions["settings"],
            account.email,
            f"Уплатата по {invoice.number} е примена",
            render_template(
                "checkout/paid_mail.txt",
                invoice=invoice,
                days=prices().report.delivery_working_days,
                link=url_for("checkout.order", order_id=order.id, _external=True),
                **_what(db, order),
            ),
        )
        return True
    except (mail.MailNotConfigured, OSError):
        current_app.logger.exception("payment notice for %s not mailed", invoice.number)
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
            **_what(db, found),
        )


@bp.get("/<uuid:order_id>/profaktura.pdf")
def proforma_pdf(order_id: uuid.UUID):
    account_id, away = _signed_in_or_redirect()
    if away:
        return away
    with _sessions()() as db:
        found = _own_order(db, order_id, account_id)
        invoice = _proforma(db, found.id)
        document = proforma.pdf(invoice, found, description=proforma.describe(db, found))
    return current_app.response_class(
        document,
        mimetype="application/pdf",
        # Headers are Latin-1: an ASCII name, and the real one per RFC 5987.
        headers={
            "Content-Disposition": 'inline; filename="profaktura.pdf"; '
            f"filename*=UTF-8''{quote(invoice.number)}.pdf"
        },
    )


# ------------------------------------------------------------------ delivered (P4 s53)


def _delivered_pdf(order_id: uuid.UUID, which: str):
    """A delivered PDF as it was sent: from the store, never printed again."""
    account_id, away = _signed_in_or_redirect()
    if away:
        return away
    with _sessions()() as db:
        found = _own_order(db, order_id, account_id)
        if found.state not in (OrderState.DELIVERED, OrderState.REFUNDED):
            abort(404)
        if which == "report":
            if service.sku_of(db, found) == service.PACKAGE:
                abort(404)  # a package is served as its archive (package_zip)
            key = found.report_storage_key
            name = f"Извештај {_proforma(db, found.id).number}.pdf"
        else:
            invoice = db.scalar(
                select(Invoice).where(
                    Invoice.order_id == found.id, Invoice.kind == InvoiceKind.FINAL
                )
            )
            key, name = invoice.pdf_storage_key, f"{invoice.number}.pdf"
    document = deliver.stored(SnapshotStore(current_app.extensions["settings"].snapshot_dir), key)
    return current_app.response_class(
        document,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="document.pdf"; '
            f"filename*=UTF-8''{quote(name)}"
        },
    )


@bp.get("/<uuid:order_id>/izveshtaj.pdf")
def report_pdf(order_id: uuid.UUID):
    return _delivered_pdf(order_id, "report")


@bp.get("/<uuid:order_id>/paket.zip")
def package_zip(order_id: uuid.UUID):
    """A delivered package, exactly as it was sent: the forms and the checklist."""
    account_id, away = _signed_in_or_redirect()
    if away:
        return away
    with _sessions()() as db:
        found = _own_order(db, order_id, account_id)
        if found.state not in (OrderState.DELIVERED, OrderState.REFUNDED):
            abort(404)
        if service.sku_of(db, found) != service.PACKAGE:
            abort(404)
        key, number = found.report_storage_key, _proforma(db, found.id).number
    document = deliver.stored(SnapshotStore(current_app.extensions["settings"].snapshot_dir), key)
    return current_app.response_class(
        document,
        mimetype="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="paket.zip"; '
            f"filename*=UTF-8''{quote(f'Пакет {number}.zip')}"
        },
    )


@bp.get("/<uuid:order_id>/faktura.pdf")
def invoice_pdf(order_id: uuid.UUID):
    return _delivered_pdf(order_id, "invoice")
