"""Creating an order, asking for payment, confirming it (roadmap P4 s48).

Nothing here knows which provider an order has: it asks `providers.provider_for(order)`, and
the state machine (`states.move`) is the only way an order's state changes.

**The price is `config/prices.yaml`'s** (docs/decisions.md D1), never a template's and never
the product row's alone: the row exists for the foreign key and is kept equal to the file.
The founding price applies while it is open and fewer than its limit of orders have taken it;
a cancelled order gives its place back.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.commerce import Order, Product
from app.models.enums import OrderState
from app.orders import numbering, states
from app.orders.providers import Evidence, PaymentRequest, provider_for
from app.pricing import prices

REPORT = "report"
PACKAGE = "package"


@dataclass(frozen=True)
class Buyer:
    """The legal identity on the invoice. Never sent to a model (invariant 4)."""

    name: str
    address: str
    edb: str | None = None
    embs: str | None = None


# What each product is called and costs: config/prices.yaml, never a template (D1).
NAMES = {REPORT: "Детален извештај", PACKAGE: "Пакет на документи"}


def _list_price(sku: str) -> int:
    return prices().package.net if sku == PACKAGE else prices().report.net


def ensure_product(session: Session, sku: str = REPORT) -> Product:
    """The product row for the foreign key, its price kept equal to config/prices.yaml."""
    net, vat = _list_price(sku), prices().vat_percent
    product = session.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        product = Product(sku=sku, name_mk=NAMES[sku], price_mkd=net, vat_rate=vat)
        session.add(product)
    else:
        product.price_mkd, product.vat_rate = net, vat
    session.flush()
    return product


def report_price(session: Session) -> int:
    """The net price a new report order pays: the founding price while it lasts."""
    p = prices()
    founding = p.report.founding
    if founding.open:
        taken = session.scalar(
            select(func.count())
            .select_from(Order)
            .join(Product, Product.id == Order.product_id)
            .where(
                Product.sku == REPORT,
                Order.amount_mkd == founding.net,
                Order.state != OrderState.CANCELLED,
            )
        )
        if taken < founding.orders:
            return founding.net
    return p.report.net


def _create(session, sku, net, account_id, profile_id, buyer, provider, today):
    product = ensure_product(session, sku)
    order = Order(
        account_id=account_id,
        profile_id=profile_id,
        product_id=product.id,
        state=OrderState.CREATED,
        amount_mkd=net,
        vat_mkd=prices().gross(net) - net,
        provider=provider,
        buyer_name=buyer.name,
        buyer_address=buyer.address,
        buyer_edb=buyer.edb,
        buyer_embs=buyer.embs,
    )
    session.add(order)
    session.flush()
    request = provider_for(order).request(session, order, today or numbering.today())
    states.move(order, OrderState.INVOICED)
    session.flush()
    return order, request


def create(
    session: Session,
    account_id,
    profile_id,
    buyer: Buyer,
    *,
    provider: str = "invoice",
    today: dt.date | None = None,
) -> tuple[Order, PaymentRequest]:
    """A new report order, billed at once: returns it and what the customer pays with."""
    net = report_price(session)
    return _create(session, REPORT, net, account_id, profile_id, buyer, provider, today)


def create_package(
    session: Session,
    account_id,
    profile_id,
    call_id,
    buyer: Buyer,
    *,
    provider: str = "invoice",
    today: dt.date | None = None,
) -> tuple[Order, PaymentRequest]:
    """A new document-package order for one call (P5 s75), billed at once.

    The package row is written with the order, so the call it is for is fixed when the
    customer pays, whatever the shortlist says later.
    """
    from app.models.documents import DocumentPackage

    order, request = _create(
        session, PACKAGE, prices().package.net, account_id, profile_id, buyer, provider, today
    )
    session.add(DocumentPackage(order_id=order.id, call_id=call_id))
    session.flush()
    return order, request


def sku_of(session: Session, order: Order) -> str:
    return session.scalar(select(Product.sku).where(Product.id == order.product_id))


def confirm_payment(session: Session, order: Order, evidence: Evidence) -> None:
    """The money arrived: the provider records it, and the order is paid."""
    provider_for(order).confirm(session, order, evidence)
    states.move(order, OrderState.PAID)
    session.flush()


def cancel(session: Session, order: Order) -> None:
    """Before payment only (the state machine refuses otherwise)."""
    states.move(order, OrderState.CANCELLED)
    session.flush()
