"""Products, orders, invoices and subscriptions.

v1 billing is a proforma invoice plus bank transfer in denars, reconciled by hand.
Neither Stripe nor PayPal can receive money in North Macedonia (brief section 3.2),
so the provider column exists to let a local card gateway slot in later without
order logic changing.
"""

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, now_column, pg_enum, timestamptz, uuid_pk
from app.models.enums import InvoiceKind, OrderState


class Product(Base):
    __tablename__ = "product"

    id: Mapped[uuid.UUID] = uuid_pk()
    sku: Mapped[str] = mapped_column(String(50), unique=True)
    name_mk: Mapped[str] = mapped_column(Text)
    # Ex-VAT. The UI shows both figures, because B2B buyers think ex-VAT while
    # farmers and individuals are not VAT-registered and pay the gross.
    price_mkd: Mapped[float] = mapped_column(Numeric(12, 2))
    vat_rate: Mapped[float] = mapped_column(Numeric(5, 2), server_default=text("18.00"))
    is_recurring: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Order(Base):
    __tablename__ = "order"
    __table_args__ = (
        Index("ix_order_state", "state", "created_at"),
        Index("ix_order_account", "account_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id", ondelete="RESTRICT"))
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applicant_profile.id"))
    match_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("match_run.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.id"))
    state: Mapped[OrderState] = mapped_column(
        pg_enum(OrderState, "order_state"), server_default=text("'created'")
    )
    amount_mkd: Mapped[float] = mapped_column(Numeric(12, 2))
    vat_mkd: Mapped[float] = mapped_column(Numeric(12, 2))
    provider: Mapped[str] = mapped_column(String(30), server_default=text("'invoice'"))

    # Legal identity of the buyer, collected for the invoice only. These columns
    # must never reach a model payload (CLAUDE.md invariant 4).
    buyer_name: Mapped[str | None] = mapped_column(Text)
    buyer_address: Mapped[str | None] = mapped_column(Text)
    buyer_edb: Mapped[str | None] = mapped_column(String(20))
    buyer_embs: Mapped[str | None] = mapped_column(String(20))

    created_at: Mapped[dt.datetime] = now_column()
    delivered_at: Mapped[dt.datetime | None] = timestamptz()


class Invoice(Base):
    __tablename__ = "invoice"
    __table_args__ = (
        Index("ix_invoice_unpaid", "issued_at", postgresql_where=text("paid_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order.id", ondelete="RESTRICT"))
    kind: Mapped[InvoiceKind] = mapped_column(pg_enum(InvoiceKind, "invoice_kind"))
    # Gapless per fiscal year; the numbering scheme must match what the
    # accountant already files (docs/decisions.md D4).
    number: Mapped[str] = mapped_column(String(50), unique=True)
    fiscal_year: Mapped[int] = mapped_column(SmallInteger)
    issued_at: Mapped[dt.date] = mapped_column(Date)
    due_at: Mapped[dt.date | None] = mapped_column(Date)
    amount_mkd: Mapped[float] = mapped_column(Numeric(12, 2))
    vat_mkd: Mapped[float] = mapped_column(Numeric(12, 2))
    total_mkd: Mapped[float] = mapped_column(Numeric(12, 2))
    pdf_storage_key: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[dt.datetime | None] = timestamptz()
    bank_reference: Mapped[str | None] = mapped_column(Text)
    reconciled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("account.id"))


class Subscription(Base):
    """The monitoring subscription: the line that fixes seasonality (risks R4)."""

    __tablename__ = "subscription"
    __table_args__ = (
        Index(
            "ix_subscription_due",
            "renews_on",
            postgresql_where=text("cancelled_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applicant_profile.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.id"))
    started_on: Mapped[dt.date] = mapped_column(Date)
    renews_on: Mapped[dt.date] = mapped_column(Date)
    cancelled_at: Mapped[dt.datetime | None] = timestamptz()
    last_alert_at: Mapped[dt.datetime | None] = timestamptz()
