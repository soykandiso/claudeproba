"""The monitoring subscription (roadmap P6 s76): paid periods, never a hidden renewal.

A subscription is paid the way everything here is: an order, a proforma, a bank transfer, a
person reconciling it. Payment **starts** a subscription (from the payment date) or **extends**
one (from the end of the period already paid, so an early renewal loses no day), and the
invoice for the period is issued and mailed at once. The period is a calendar month or year:
31 January plus a month is 28 (or 29) February, the last day that exists.

**Nothing renews by itself.** There is no card on file and no automatic charge: before a
period ends a renewal proforma is issued (P6 s79) and the subscription goes on only if it is
paid. Cancelling stops that; the period already paid runs to its end, with no refund to
compute. Status is read from the dates, not stored: active, ending (cancelled, still paid),
or lapsed (its period over).

**The subscription follows the account's current profile.** A profile edit makes a new
version and leaves the old ones as they were (architecture §9.3); the subscription keeps the
version it was bought with (`profile_id`) and alerts match the newest one, each alert
recording which version it matched (s78).
"""

import calendar
import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, ApplicantProfile
from app.models.commerce import Invoice, Order, Product, Subscription
from app.models.enums import InvoiceKind, OrderState
from app.orders import numbering, service, states
from app.reports.lint import find_banned
from app.web.format import SKOPJE, mkdate

PLANS = {service.MONTH: 1, service.YEAR: 12}  # months per period


class SubscriptionRefused(ValueError):
    """Nothing was started, extended or sent. The message is the operator's."""


def add_months(day: dt.date, months: int) -> dt.date:
    """The same day `months` later, or the last day of that month if it has fewer days."""
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def status(subscription: Subscription, today: dt.date) -> str:
    """«active», «ending» (cancelled, the paid period still running) or «lapsed»."""
    if subscription.renews_on <= today:
        return "lapsed"
    return "ending" if subscription.cancelled_at else "active"


def current(session: Session, account_id) -> Subscription | None:
    """The account's newest subscription, whatever its status."""
    return session.scalar(
        select(Subscription)
        .where(Subscription.account_id == account_id)
        .order_by(Subscription.started_on.desc(), Subscription.renews_on.desc())
    )


def monitored_profile(session: Session, subscription: Subscription) -> ApplicantProfile | None:
    """The profile alerts are matched against: the account's newest version."""
    return session.scalar(
        select(ApplicantProfile)
        .where(ApplicantProfile.account_id == subscription.account_id)
        .order_by(ApplicantProfile.version.desc(), ApplicantProfile.created_at.desc())
    )


def order(
    session: Session,
    account_id,
    profile_id,
    plan: str,
    buyer: service.Buyer,
    *,
    renewing: Subscription | None = None,
    today: dt.date | None = None,
):
    """A monitoring order, billed at once: the first period, or the next one of `renewing`."""
    if plan not in PLANS:
        raise SubscriptionRefused(f"no such plan: {plan}")
    placed, request = service._create(
        session,
        plan,
        service._list_price(plan),
        account_id,
        profile_id,
        buyer,
        "invoice",
        today,
    )
    placed.subscription_id = renewing.id if renewing else None
    session.flush()
    return placed, request


@dataclass(frozen=True)
class Activated:
    subscription_id: object
    until: dt.date
    invoice_number: str
    to: str


def activate(
    session: Session, store, settings, order_id, *, now: dt.datetime | None = None
) -> Activated:
    """A paid monitoring order starts or extends its subscription; the invoice is mailed.

    All or nothing, the e-mail last: if it fails, no invoice number is spent and the order
    stays paid, for the sweep or the operator to try again.
    """
    from app import mail
    from app.orders import deliver, proforma

    now = now or numbering.now()
    today = now.astimezone(SKOPJE).date()
    placed = session.get(Order, order_id)
    if placed is None or placed.state != OrderState.PAID:
        raise SubscriptionRefused("Нарачката не е платена или е веќе активирана.")
    sku = session.scalar(select(Product.sku).where(Product.id == placed.product_id))
    if sku not in PLANS:
        raise SubscriptionRefused("Нарачката не е за следење.")
    paid = session.scalar(
        select(Invoice).where(Invoice.order_id == placed.id, Invoice.kind == InvoiceKind.PROFORMA)
    )
    try:
        if placed.subscription_id:
            subscription = session.get(Subscription, placed.subscription_id)
            start = max(subscription.renews_on, today)  # an early renewal loses no day
            subscription.renews_on = add_months(start, PLANS[sku])
            subscription.product_id = placed.product_id
            subscription.cancelled_at = None  # paying again is wanting it again
        else:
            start = today
            subscription = Subscription(
                account_id=placed.account_id,
                profile_id=placed.profile_id,
                product_id=placed.product_id,
                started_on=today,
                renews_on=add_months(today, PLANS[sku]),
            )
            session.add(subscription)
            session.flush()
            placed.subscription_id = subscription.id
        invoice = deliver._issue(session, placed, paid, today)
        period = (start, subscription.renews_on)
        invoice_pdf = proforma.pdf(
            invoice, placed, paid, proforma.describe(session, placed, period=period)
        )
        invoice.pdf_storage_key = deliver._keep(store, placed, invoice_pdf)
        # A period has no document of its own: what was delivered is the invoice for it.
        placed.report_storage_key = invoice.pdf_storage_key
        states.move(placed, OrderState.IN_PROGRESS)
        states.move(placed, OrderState.DELIVERED)
        placed.delivered_at = now
        session.flush()

        account = session.get(Account, placed.account_id)
        body = (
            "Здраво,\n\n"
            f"Уплатата по профактурата {paid.number} ја примивме. Следењето на нови повици за "
            f"вашиот профил е активно до {mkdate(subscription.renews_on)}.\n\n"
            "Кога ќе се објави нов повик што одговара на профилот, ви пишуваме, со цитат од "
            "условите и врска до повикот. Пред крајот на периодот ви праќаме профактура за "
            "продолжување; ако не ја платите, следењето престанува, без никаква обврска.\n\n"
            f"Во прилог е фактурата {invoice.number}.\n\nГрантови и субвенции\n"
        )
        banned = find_banned(body)
        if banned:
            raise proforma.ProformaRefused(f"banned phrase in the activation e-mail: {banned}")
        mail.send(
            settings,
            account.email,
            f"Следењето е активно до {mkdate(subscription.renews_on)}",
            body,
            attachments=((f"{invoice.number}.pdf", invoice_pdf, "application/pdf"),),
        )
    except (mail.MailNotConfigured, OSError) as failed:
        session.rollback()
        raise SubscriptionRefused(
            f"Е-поштата не замина ({failed}); ништо не е активирано."
        ) from None
    except proforma.ProformaRefused as refused:
        session.rollback()
        raise SubscriptionRefused(f"Фактурата не може да се отпечати: {refused}") from None
    session.commit()
    return Activated(subscription.id, subscription.renews_on, invoice.number, account.email)


def cancel(session: Session, subscription: Subscription, *, now: dt.datetime | None = None) -> None:
    """No renewal; the period already paid runs to its end."""
    if subscription.cancelled_at is None:
        subscription.cancelled_at = now or numbering.now()
        session.flush()
