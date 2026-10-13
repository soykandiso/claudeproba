"""Delivering a paid report (roadmap P4 s53): the approved PDF and the invoice, e-mailed at once.

A report reaches a customer only through review (`app/review/report.py`): delivery is what
approving a paid order's report does next. In order, in one transaction:

1. the order is `in_progress` and its run (`order.match_run_id`) has an approved report;
2. the report is printed with every check run again (`render.render`): a call that closed
   since approval stops it here, and the operator is told;
3. the invoice is issued (`Ф-…`, gapless per year), settling the paid proforma;
4. both PDFs are kept in the snapshot store as sent (backed up with it): a report cannot be
   printed again once a call it cites closes, and an invoice is the document the buyer files;
5. the e-mail goes out with both attached;
6. the order is `delivered`, and everything commits.

**The e-mail is the last thing before the commit.** If it fails, everything rolls back: no
invoice number is spent (numbers stay gapless) and the order stays `in_progress`, for the
operator to send again from the report's page. The PDFs already written to the store are
harmless: content-addressed, unreferenced, the same bytes next time.
"""

import datetime as dt
import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import jinja2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mail
from app.models import Account, ReviewQueueItem
from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind, OrderState, ReviewKind
from app.orders import numbering, proforma, states
from app.reports import render
from app.reports.lint import find_banned
from app.web.format import SKOPJE, mkdate

TEMPLATES = Path(__file__).resolve().parent / "templates"


class Refused(ValueError):
    """Nothing was sent and nothing changed. The message is the operator's."""


@dataclass(frozen=True)
class Delivered:
    order_id: object
    invoice_number: str
    to: str


def order_for(session: Session, item: ReviewQueueItem) -> Order | None:
    """The paid order a report review item belongs to, if any (a demo run has none)."""
    if item.kind != ReviewKind.REPORT or item.match_run_id is None:
        return None
    return session.scalar(select(Order).where(Order.match_run_id == item.match_run_id))


def _approved_report(session: Session, order: Order) -> ReviewQueueItem | None:
    return session.scalar(
        select(ReviewQueueItem)
        .where(
            ReviewQueueItem.kind == ReviewKind.REPORT,
            ReviewQueueItem.match_run_id == order.match_run_id,
            ReviewQueueItem.state.in_(render.RENDERABLE),
        )
        .order_by(ReviewQueueItem.resolved_at.desc())
    )


def _proforma(session: Session, order: Order) -> Invoice:
    return session.scalar(
        select(Invoice).where(Invoice.order_id == order.id, Invoice.kind == InvoiceKind.PROFORMA)
    )


def _issue(session: Session, order: Order, paid: Invoice, today: dt.date) -> Invoice:
    invoice = Invoice(
        order_id=order.id,
        kind=InvoiceKind.FINAL,
        number=numbering.next_number(session, InvoiceKind.FINAL, today.year),
        fiscal_year=today.year,
        issued_at=today,
        amount_mkd=paid.amount_mkd,
        vat_mkd=paid.vat_mkd,
        total_mkd=paid.total_mkd,
        paid_at=paid.paid_at,
        bank_reference=paid.bank_reference,
        reconciled_by=paid.reconciled_by,
    )
    session.add(invoice)
    session.flush()
    return invoice


def _keep(store, order: Order, content: bytes) -> str:
    key = f"delivered/{order.id}/{hashlib.sha256(content).hexdigest()}"
    store.put(key, content)
    return key


@cache
def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES), undefined=jinja2.StrictUndefined
    )
    env.filters["mkdate"] = mkdate
    return env


def deliver(
    session: Session,
    store,
    settings,
    order_id,
    *,
    link: str,
    now: dt.datetime | None = None,
) -> Delivered:
    """Send the order's approved report and its invoice, or raise Refused having changed nothing."""
    now = now or dt.datetime.now(dt.UTC)
    today = now.astimezone(SKOPJE).date()
    order = session.get(Order, order_id)
    if order is None:
        raise Refused("Нема таква нарачка.")
    if order.state == OrderState.DELIVERED:
        raise Refused("Нарачката е веќе испорачана.")
    if order.state != OrderState.IN_PROGRESS:
        raise Refused(f"Нарачката не е во изработка (состојба: {order.state}).")
    item = _approved_report(session, order)
    if item is None:
        raise Refused("Извештајот за оваа нарачка уште не е прифатен.")
    paid = _proforma(session, order)

    try:
        report = render.render(session, item, issued=today).pdf
    except render.RenderRefused as refused:
        raise Refused(f"Извештајот не може да се отпечати: {refused}") from None
    try:
        invoice = _issue(session, order, paid, today)
        invoice_pdf = proforma.pdf(invoice, order, paid)
        invoice.pdf_storage_key = _keep(store, order, invoice_pdf)
        order.report_storage_key = _keep(store, order, report)
        states.move(order, OrderState.DELIVERED)
        order.delivered_at = now
        session.flush()

        account = session.get(Account, order.account_id)
        body = (
            _environment()
            .get_template("delivery_mail.txt")
            .render(proforma=paid, invoice=invoice, link=link)
        )
        banned = find_banned(body)
        if banned:
            raise proforma.ProformaRefused(f"banned phrase in the delivery e-mail: {banned}")
        mail.send(
            settings,
            account.email,
            f"Вашиот детален извештај, нарачка {paid.number}",
            body,
            attachments=(
                (f"Извештај {paid.number}.pdf", report, "application/pdf"),
                (f"{invoice.number}.pdf", invoice_pdf, "application/pdf"),
            ),
        )
    except (mail.MailNotConfigured, OSError) as failed:
        session.rollback()
        raise Refused(
            f"Е-поштата не замина ({failed}); ништо не е испратено ни издадено."
        ) from None
    except proforma.ProformaRefused as refused:
        session.rollback()
        raise Refused(f"Фактурата или е-поштата не поминаа проверка: {refused}") from None
    session.commit()
    return Delivered(order.id, invoice.number, account.email)


def stored(store, key: str) -> bytes:
    """A delivered PDF, exactly as it was sent (the store checks it against its hash)."""
    return store.get(key)
