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
from app.review import report as review
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
    now = now or numbering.now()
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
    return _finish(
        session,
        store,
        settings,
        order,
        paid,
        report,
        now=now,
        subject=f"Вашиот детален извештај, нарачка {paid.number}",
        template="delivery_mail.txt",
        context={"calls": len(review.draft_of(item)["calls"]), "link": link},
        attachments=[(f"Извештај {paid.number}.pdf", report, "application/pdf")],
    )


def _finish(
    session, store, settings, order, paid, artefact, *, now, subject, template, context, attachments
) -> Delivered:
    """Issue the invoice, keep what is sent, mark the order delivered, then mail; all or nothing.

    The e-mail is the last thing before the commit: if it fails, everything rolls back, no
    invoice number is spent and the order stays in progress.
    """
    today = now.astimezone(SKOPJE).date()
    try:
        invoice = _issue(session, order, paid, today)
        invoice_pdf = proforma.pdf(invoice, order, paid)
        invoice.pdf_storage_key = _keep(store, order, invoice_pdf)
        # The artefact as delivered: the report's PDF, or a package's archive (P5 s75).
        order.report_storage_key = _keep(store, order, artefact)
        states.move(order, OrderState.DELIVERED)
        order.delivered_at = now
        session.flush()

        account = session.get(Account, order.account_id)
        body = (
            _environment().get_template(template).render(proforma=paid, invoice=invoice, **context)
        )
        banned = find_banned(body)
        if banned:
            raise proforma.ProformaRefused(f"banned phrase in the delivery e-mail: {banned}")
        mail.send(
            settings,
            account.email,
            subject,
            body,
            attachments=(
                *attachments,
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


# ------------------------------------------------------------------ a document package (P5 s75)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CHECKLIST_NAME = "Што уште треба да подготвите"


def package_item(session: Session, order: Order) -> ReviewQueueItem | None:
    """The newest review item of an order's package, whatever its state."""
    return session.scalar(
        select(ReviewQueueItem)
        .where(
            ReviewQueueItem.order_id == order.id,
            ReviewQueueItem.kind == ReviewKind.DOCUMENT_PACKAGE,
        )
        .order_by(ReviewQueueItem.id.desc())
    )


_NOT_IN_FILENAMES = set('\\/:*?"<>|')


def _filename(n: int, title: str) -> str:
    safe = "".join(c for c in title if c not in _NOT_IN_FILENAMES).strip()
    return f"{n}. {safe[:80]}.docx"


def package_files(store, item: ReviewQueueItem) -> list[tuple[str, bytes]]:
    """The package's documents as stored, named in order, the checklist last."""
    files = [
        (_filename(n, d["title_mk"]), store.get(d["key"]))
        for n, d in enumerate(item.payload["documents"], 1)
    ]
    files.append((f"{CHECKLIST_NAME}.docx", store.get(item.payload["checklist_key"])))
    return files


def _archive(files: list[tuple[str, bytes]]) -> bytes:
    import io
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files:
            archive.writestr(name, content)
    return out.getvalue()


def deliver_package(
    session: Session,
    store,
    settings,
    order_id,
    *,
    link: str,
    now: dt.datetime | None = None,
) -> Delivered:
    """Send an approved package and its invoice, or raise Refused having changed nothing."""
    now = now or numbering.now()
    order = session.get(Order, order_id)
    if order is None:
        raise Refused("Нема таква нарачка.")
    if order.state == OrderState.DELIVERED:
        raise Refused("Нарачката е веќе испорачана.")
    if order.state != OrderState.IN_PROGRESS:
        raise Refused(f"Нарачката не е во изработка (состојба: {order.state}).")
    item = package_item(session, order)
    if item is None or item.state not in render.RENDERABLE:
        raise Refused("Пакетот за оваа нарачка уште не е прифатен.")
    files = package_files(store, item)
    paid = _proforma(session, order)
    return _finish(
        session,
        store,
        settings,
        order,
        paid,
        _archive(files),
        now=now,
        subject=f"Вашиот пакет на документи, нарачка {paid.number}",
        template="delivery_package_mail.txt",
        context={"title": item.payload["title_mk"], "link": link},
        attachments=[(name, content, DOCX) for name, content in files],
    )
