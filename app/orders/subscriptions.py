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
import logging
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
log = logging.getLogger(__name__)


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
            if subscription.cancelled_at is not None:  # paying again is wanting it again
                subscription.cancelled_at = None
                _consent(session, subscription.account_id, True, None)
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
            _consent(session, placed.account_id, True, None)  # ordering it is asking for it
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


ALERTS = "alerts"  # the consent purpose: mail about new calls (P6 s80)


def _consent(session: Session, account_id, granted: bool, ip: str | None) -> None:
    from app.legal import legal
    from app.models import ConsentRecord

    session.add(
        ConsentRecord(
            account_id=account_id,
            purpose=ALERTS,
            granted=granted,
            policy_version=legal().version,
            ip_address=ip,
        )
    )


def cancel(
    session: Session, subscription: Subscription, *, now: dt.datetime | None = None, ip=None
) -> None:
    """Stop alerts now and renew nothing (P6 s80); the period paid is not refunded."""
    if subscription.cancelled_at is None:
        subscription.cancelled_at = now or numbering.now()
        _consent(session, subscription.account_id, False, ip)
        session.flush()


def resume(session: Session, subscription: Subscription, today: dt.date, *, ip=None) -> bool:
    """Undo a cancellation while the paid period runs. False when it has ended."""
    if subscription.cancelled_at is None or subscription.renews_on <= today:
        return False
    subscription.cancelled_at = None
    _consent(session, subscription.account_id, True, ip)
    session.flush()
    return True


def _serializer(secret: str):
    from itsdangerous import URLSafeSerializer

    return URLSafeSerializer(secret, salt="unsubscribe")


def unsubscribe_token(secret: str, subscription_id) -> str:
    """For the link in every alert and renewal e-mail: it names the subscription, nothing else."""
    return _serializer(secret).dumps(str(subscription_id))


def from_token(secret: str, token: str) -> str | None:
    from itsdangerous import BadSignature

    try:
        return _serializer(secret).loads(token)
    except BadSignature:
        return None


# ------------------------------------------------------------------ renewals (P6 s79)


@dataclass(frozen=True)
class Renewal:
    subscription_id: object
    number: str
    period: tuple[dt.date, dt.date]


def _open_renewal(session: Session, subscription: Subscription) -> Order | None:
    return session.scalar(
        select(Order).where(
            Order.subscription_id == subscription.id,
            Order.state.in_([OrderState.CREATED, OrderState.INVOICED]),
        )
    )


def due_for_renewal(session: Session, today: dt.date, notice_days: int) -> list[Subscription]:
    """Running, not cancelled, ending within `notice_days`, with no renewal proforma open."""
    candidates = session.scalars(
        select(Subscription).where(
            Subscription.cancelled_at.is_(None),
            Subscription.renews_on > today,
            Subscription.renews_on <= today + dt.timedelta(days=notice_days),
        )
    ).all()
    return [s for s in candidates if _open_renewal(session, s) is None]


def _last_buyer(session: Session, subscription: Subscription) -> service.Buyer:
    """The invoice details of the subscription's last order: a renewal is billed the same way."""
    last = session.scalar(
        select(Order)
        .where(Order.subscription_id == subscription.id)
        .order_by(Order.created_at.desc())
    )
    return service.Buyer(last.buyer_name, last.buyer_address, last.buyer_edb, last.buyer_embs)


def renew(session: Session, settings, subscription: Subscription, today: dt.date, link) -> Renewal:
    """Issue and mail the renewal proforma; all or nothing, the e-mail last.

    `link(subscription)` is the subscription's one-click unsubscribe address.
    """
    from app import mail
    from app.orders import proforma

    sku = session.scalar(select(Product.sku).where(Product.id == subscription.product_id))
    profile = monitored_profile(session, subscription)
    try:
        placed, _ = order(
            session,
            subscription.account_id,
            profile.id if profile else subscription.profile_id,
            sku,
            _last_buyer(session, subscription),
            renewing=subscription,
            today=today,
        )
        invoice = session.scalar(
            select(Invoice).where(
                Invoice.order_id == placed.id, Invoice.kind == InvoiceKind.PROFORMA
            )
        )
        period = (subscription.renews_on, add_months(subscription.renews_on, PLANS[sku]))
        document = proforma.pdf(
            invoice, placed, description=proforma.describe(session, placed, period=period)
        )
        body = (
            "Здраво,\n\n"
            "Следењето на нови повици за вашиот профил е активно до "
            f"{mkdate(subscription.renews_on)}. "
            f"За продолжување до {mkdate(period[1])}, во прилог е профактурата {invoice.number}, "
            f"со рок за плаќање {mkdate(invoice.due_at)}.\n\n"
            "Ако не ја платите, следењето престанува на крајот на периодот, без никаква обврска: "
            "не наплатуваме ништо што не сте го платиле. Ако веќе не сакате да ве известуваме, "
            f"откажете го следењето со еден клик: {link(subscription)}\n\n"
            "Грантови и субвенции\n"
        )
        banned = find_banned(body)
        if banned:
            raise proforma.ProformaRefused(f"banned phrase in the renewal e-mail: {banned}")
        account = session.get(Account, subscription.account_id)
        mail.send(
            settings,
            account.email,
            f"Продолжување на следењето: профактура {invoice.number}",
            body,
            attachments=((f"{invoice.number}.pdf", document, "application/pdf"),),
            headers=mail.unsubscribe_headers(link(subscription)),
        )
    except (mail.MailNotConfigured, OSError) as failed:
        session.rollback()
        raise SubscriptionRefused(
            f"Е-поштата не замина ({failed}); профактурата не е издадена."
        ) from None
    except proforma.ProformaRefused as refused:
        session.rollback()
        raise SubscriptionRefused(f"Профактурата не може да се отпечати: {refused}") from None
    session.commit()
    return Renewal(subscription.id, invoice.number, period)


def issue_renewals(session: Session, settings, today: dt.date, notice_days: int, link) -> dict:
    """Every renewal due today, each on its own: one failure holds no one else up."""
    counts = {"issued": 0, "failed": 0}
    for subscription in due_for_renewal(session, today, notice_days):
        try:
            renew(session, settings, subscription, today, link)
            counts["issued"] += 1
        except SubscriptionRefused:
            log.exception(
                "renewal for subscription %s not issued; tried again tomorrow", subscription.id
            )
            counts["failed"] += 1
    return counts
