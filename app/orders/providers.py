"""Who takes the money (roadmap P4 s48, brief §3.2, docs/architecture.md §3.6).

`PaymentProvider` is everything the order logic knows about payment: ask for it, and be told
it arrived. `InvoiceProvider` does it the way B2B already works here: a proforma, a bank
transfer in denars, and a person matching the statement line to the proforma (P4 s51). A card
gateway is a second class with the same two methods, registered in `PROVIDERS` under the name
an order carries in `order.provider`; `app/orders/service.py` does not change.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind
from app.orders import numbering


@dataclass(frozen=True)
class PaymentRequest:
    """What the customer is given to pay with: a proforma's number, or a gateway's page."""

    kind: str  # "proforma" or "redirect"
    reference: str  # the proforma's number, or the gateway's address
    due: dt.date | None
    total_mkd: float


@dataclass(frozen=True)
class Evidence:
    """That the money arrived: a bank statement's reference, or a gateway's transaction id."""

    reference: str
    by: object | None = None  # the account that reconciled it, when a person did
    at: dt.datetime | None = None


class PaymentNotFound(LookupError):
    """There is nothing of this order's to confirm (no proforma was issued)."""


class PaymentProvider(Protocol):
    name: str

    def request(self, session: Session, order: Order, today: dt.date) -> PaymentRequest:
        """Ask for the money. Called once, when the order is created."""

    def confirm(self, session: Session, order: Order, evidence: Evidence) -> None:
        """Record that the money arrived. Raises PaymentNotFound if nothing was asked for."""


class InvoiceProvider:
    """A proforma, a bank transfer, a person reconciling it."""

    name = "invoice"

    def request(self, session: Session, order: Order, today: dt.date) -> PaymentRequest:
        due = today + dt.timedelta(days=numbering.settings()["proforma_due_days"])
        total = float(order.amount_mkd) + float(order.vat_mkd)
        proforma = Invoice(
            order_id=order.id,
            kind=InvoiceKind.PROFORMA,
            number=numbering.next_number(session, InvoiceKind.PROFORMA, today.year),
            fiscal_year=today.year,
            issued_at=today,
            due_at=due,
            amount_mkd=order.amount_mkd,
            vat_mkd=order.vat_mkd,
            total_mkd=total,
        )
        session.add(proforma)
        session.flush()
        return PaymentRequest("proforma", proforma.number, due, total)

    def confirm(self, session: Session, order: Order, evidence: Evidence) -> None:
        proforma = session.scalar(
            select(Invoice).where(
                Invoice.order_id == order.id, Invoice.kind == InvoiceKind.PROFORMA
            )
        )
        if proforma is None:
            raise PaymentNotFound(f"order {order.id} has no proforma to mark paid")
        proforma.paid_at = evidence.at or dt.datetime.now(dt.UTC)
        proforma.bank_reference = evidence.reference
        proforma.reconciled_by = evidence.by


PROVIDERS: dict[str, PaymentProvider] = {InvoiceProvider.name: InvoiceProvider()}


def provider_for(order: Order) -> PaymentProvider:
    try:
        return PROVIDERS[order.provider or InvoiceProvider.name]
    except KeyError:
        raise LookupError(
            f"order {order.id}: no payment provider called {order.provider!r}"
        ) from None
