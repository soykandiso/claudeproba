"""Matching a bank statement line to a proforma (roadmap P4 s51).

The operator pastes a line from the bank statement; this finds the proforma numbers in it
and the amounts, and says which open proforma it is. Confirming is a second, separate step
and the only one that changes anything: `confirm` checks the amount to the denar and moves
the order to paid through `service.confirm_payment`, the one way an order is paid.

**Nothing here guesses.** A line that names no open proforma is matched to none; an amount
that is not the proforma's total is refused, not marked paid in part. A partial or doubled
payment is a conversation with the customer and the accountant, not a state.

Banks often send the purpose of payment transliterated (`PF-2026-0001`) or with the dashes
lost (`ПФ 2026 0001`); both are read as the number they stand for.
"""

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from babel.numbers import format_decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind, OrderState
from app.orders import numbering, service, states
from app.orders.providers import Evidence

# The prefix as issued (ПФ), or as a bank's Latin alphabet writes it (PF), then year and number.
_LATIN = {"ПФ": "PF", "Ф": "F"}
_CENT = Decimal("0.01")


def _number_pattern() -> re.Pattern:
    prefix = numbering.settings()["prefixes"]["proforma"]
    spellings = "|".join(re.escape(p) for p in {prefix, _LATIN.get(prefix, prefix)})
    return re.compile(rf"(?<![\w])(?:{spellings})\W{{0,3}}(20\d\d)\W{{0,3}}(\d{{1,4}})(?!\d)", re.I)


# 5.782,00 · 5782,00 · 5,782.00 · 5782.00 · 5782 (with МКД/MKD/ден after it).
_AMOUNT = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.\s]\d{3})+,\d{2}|\d+,\d{2}|\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})(?![\d])"
    r"|(?<![\d.,])(\d+)\s*(?:МКД|MKD|ден)",
    re.I,
)


def _mk(value: Decimal) -> str:
    """5.782,00, as the statement and the proforma write it, whatever page is open."""
    return format_decimal(value, format="#,##0.00", locale="mk")


class Refused(ValueError):
    """A confirmation that would record something untrue. The message is the operator's."""


@dataclass(frozen=True)
class Open:
    """An open proforma and the order it bills, as the operator sees it."""

    invoice: Invoice
    order: Order

    @property
    def overdue(self) -> bool:
        return self.invoice.due_at is not None and self.invoice.due_at < dt.date.today()


def numbers_in(line: str) -> list[str]:
    """The proforma numbers a statement line names, as issued (ПФ-2026-0001), in order."""
    prefix = numbering.settings()["prefixes"]["proforma"]
    found = []
    for year, n in _number_pattern().findall(line or ""):
        number = f"{prefix}-{year}-{int(n):04d}"
        if number not in found:
            found.append(number)
    return found


def _decimal(text: str) -> Decimal | None:
    """5.782,00 or 5,782.00 or 5782: whichever separator comes last is the decimal one."""
    text = text.replace(" ", "").replace("\N{NO-BREAK SPACE}", "")
    if "," in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return Decimal(text).quantize(_CENT)
    except InvalidOperation:
        return None


def amounts_in(line: str) -> list[Decimal]:
    """The amounts a statement line shows."""
    found = (_decimal(decimal or whole) for decimal, whole in _AMOUNT.findall(line or ""))
    return [a for a in found if a is not None]


def amount(text: str) -> Decimal | None:
    """One amount as the operator typed it, or None when it is not one."""
    text = (text or "").strip()
    return _decimal(text) if re.fullmatch(r"\d[\d.,\s]*", text) else None


def open_proformas(session: Session) -> list[Open]:
    """Every proforma waiting for money, the oldest first."""
    rows = session.execute(
        select(Invoice, Order)
        .join(Order, Order.id == Invoice.order_id)
        .where(
            Invoice.kind == InvoiceKind.PROFORMA,
            Invoice.paid_at.is_(None),
            Order.state == OrderState.INVOICED,
        )
        .order_by(Invoice.issued_at, Invoice.number)
    ).all()
    return [Open(invoice, order) for invoice, order in rows]


def recently_paid(session: Session, limit: int = 10) -> list[Open]:
    """The last proformas marked paid, newest first: to see that a confirmation took."""
    rows = session.execute(
        select(Invoice, Order)
        .join(Order, Order.id == Invoice.order_id)
        .where(Invoice.kind == InvoiceKind.PROFORMA, Invoice.paid_at.is_not(None))
        .order_by(Invoice.paid_at.desc(), Invoice.number.desc())
        .limit(limit)
    ).all()
    return [Open(invoice, order) for invoice, order in rows]


@dataclass(frozen=True)
class Match:
    """What a statement line was found to be: an open proforma, and whether the amount is its."""

    open: Open
    amount_matches: bool


def match(session: Session, line: str) -> tuple[list[Match], list[str]]:
    """The open proformas a line names, and the numbers it names that are not open."""
    named = numbers_in(line)
    amounts = amounts_in(line)
    by_number = {o.invoice.number: o for o in open_proformas(session)}
    matches = [
        Match(by_number[n], Decimal(by_number[n].invoice.total_mkd).quantize(_CENT) in amounts)
        for n in named
        if n in by_number
    ]
    return matches, [n for n in named if n not in by_number]


def confirm(
    session: Session,
    invoice_id,
    paid: Decimal | None,
    reference: str,
    on: dt.date,
    by=None,
) -> Order:
    """Mark the proforma paid and the order with it, or raise Refused saying why not."""
    invoice = session.get(Invoice, invoice_id)
    if invoice is None or invoice.kind != InvoiceKind.PROFORMA:
        raise Refused("Нема таква профактура.")
    order = session.get(Order, invoice.order_id)
    if invoice.paid_at is not None:
        raise Refused(f"Профактурата {invoice.number} е веќе означена како платена.")
    reference = (reference or "").strip()
    if not reference:
        raise Refused("Внесете ја референцата од изводот, за уплатата да може да се најде.")
    total = Decimal(invoice.total_mkd).quantize(_CENT)
    if paid is None:
        raise Refused("Внесете го уплатениот износ како што е на изводот.")
    if paid != total:
        raise Refused(
            f"Уплатени се {_mk(paid)} МКД, а профактурата е на {_mk(total)} МКД. "
            "Делумна или двојна уплата не се означува тука: договорете се "
            "со купувачот и сметководителот."
        )
    if on > dt.date.today():
        raise Refused("Датумот на уплата не може да биде во иднина.")
    try:
        service.confirm_payment(
            session,
            order,
            # Noon UTC is the same calendar day in Skopje, whatever the season.
            Evidence(reference, by=by, at=dt.datetime.combine(on, dt.time(12), dt.UTC)),
        )
    except states.IllegalTransition:
        raise Refused(
            f"Нарачката за {invoice.number} не чека уплата (состојба: {order.state})."
        ) from None
    return order
