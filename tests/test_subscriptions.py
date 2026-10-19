"""The monitoring subscription (roadmap P6 s76).

The acceptance: "profile versioning preserved" (architecture §9.3). A subscription is paid
periods, started or extended by a reconciled payment, invoiced at once, never renewed by
itself; it follows the account's newest profile and changes none. Against PostgreSQL.
"""

import datetime as dt
import email
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import load_settings
from app.ingestion.snapshots import SnapshotStore
from app.matching.normalise import normalise, to_row
from app.models import ApplicantProfile
from app.models.commerce import Invoice, Order, Subscription
from app.models.enums import InvoiceKind, OrderState
from app.orders import fulfil, numbering, proforma, reconcile, service, subscriptions
from tests.test_account import ANSWERS
from tests.test_accounts import _account
from tests.test_orders import BUYER, _profile_id
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

# The business date (Skopje's), as the code under test uses it: this machine's clock may
# be on another day near midnight.
TODAY = numbering.today()  # for dates the code does not compute; compare with numbering.today()


@pytest.mark.parametrize(
    "day, months, then",
    [
        (dt.date(2027, 1, 31), 1, dt.date(2027, 2, 28)),  # the last day February has
        (dt.date(2028, 1, 31), 1, dt.date(2028, 2, 29)),  # a leap year
        (dt.date(2028, 2, 29), 12, dt.date(2029, 2, 28)),
        (dt.date(2026, 12, 15), 1, dt.date(2027, 1, 15)),  # over the year end
        (dt.date(2026, 3, 15), 1, dt.date(2026, 4, 15)),
    ],
)
def test_a_period_is_a_calendar_month_or_year(day, months, then):
    assert subscriptions.add_months(day, months) == then


def test_status_is_read_from_the_dates():
    paid = Subscription(started_on=TODAY, renews_on=TODAY + dt.timedelta(days=10))
    assert subscriptions.status(paid, TODAY) == "active"
    paid.cancelled_at = dt.datetime.now(dt.UTC)
    assert subscriptions.status(paid, TODAY) == "ending"  # cancelled, the period still paid
    assert subscriptions.status(paid, TODAY + dt.timedelta(days=10)) == "lapsed"


@pytest.fixture
def sending(tmp_path):
    settings = load_settings(
        env="testing", outbox_dir=str(tmp_path / "outbox"), snapshot_dir=str(tmp_path / "store")
    )
    return settings, SnapshotStore(tmp_path / "store"), tmp_path / "outbox"


def _paid(s, plan, *, renewing=None, account=None):
    account = account or _account(s)
    placed, request = subscriptions.order(
        s, account.id, _profile_id(s, account), plan, BUYER, renewing=renewing
    )
    pro = s.scalar(
        select(Invoice).where(Invoice.order_id == placed.id, Invoice.kind == InvoiceKind.PROFORMA)
    )
    reconcile.confirm(s, pro.id, Decimal(pro.total_mkd), "ref", TODAY)
    return account, placed


@db
def test_paying_starts_a_subscription_and_mails_the_invoice_for_the_period(registry, sending):  # noqa: F811
    settings, store, outbox = sending
    with registry[0]() as s:
        account, placed = _paid(s, service.MONTH)
        assert float(placed.amount_mkd) == 1200
        done = fulfil.subscription_job(s, settings, placed.id)
        subscription = s.get(Subscription, placed.subscription_id)
        today = numbering.today()  # read now: a long run can cross midnight
        assert subscription.started_on == today
        assert subscription.renews_on == subscriptions.add_months(today, 1)
        assert done["until"] == subscription.renews_on.isoformat()
        order = s.get(Order, placed.id)
        assert order.state == OrderState.DELIVERED and order.report_storage_key
        final = s.scalar(
            select(Invoice).where(Invoice.order_id == placed.id, Invoice.kind == InvoiceKind.FINAL)
        )
        assert store.get(order.report_storage_key) == store.get(final.pdf_storage_key)
        # A second run (the sweep) does nothing.
        assert fulfil.subscription_job(s, settings, placed.id)["skipped"]

    message = email.message_from_bytes(next(outbox.glob("*.eml")).read_bytes())
    body = (
        next(p for p in message.walk() if p.get_content_type() == "text/plain")
        .get_payload(decode=True)
        .decode()
    )
    assert "активно до" in body and "без никаква обврска" in body
    assert [p.get_filename() for p in message.walk() if p.get_filename()] == [f"{final.number}.pdf"]


@db
def test_an_early_renewal_loses_no_day_and_a_late_one_starts_today(registry, sending):  # noqa: F811
    settings, *_ = sending
    with registry[0]() as s:
        account, first = _paid(s, service.MONTH)
        fulfil.subscription_job(s, settings, first.id)
        subscription = s.get(Subscription, first.subscription_id)
        end = subscription.renews_on
        subscriptions.cancel(s, subscription)
        assert subscriptions.status(subscription, numbering.today()) == "ending"

        _, renewal = _paid(s, service.YEAR, renewing=subscription, account=account)
        fulfil.subscription_job(s, settings, renewal.id)
        assert subscription.renews_on == subscriptions.add_months(end, 12)  # from the old end
        assert subscription.cancelled_at is None  # paying again is wanting it again

        subscription.renews_on = numbering.today() - dt.timedelta(days=5)  # it lapsed
        _, late = _paid(s, service.MONTH, renewing=subscription, account=account)
        fulfil.subscription_job(s, settings, late.id)
        assert subscription.renews_on == subscriptions.add_months(numbering.today(), 1)


@db
def test_the_subscription_follows_the_newest_profile_and_changes_none(registry):  # noqa: F811
    with registry[0]() as s:
        account = _account(s)
        first = _profile_id(s, account)
        placed, _ = subscriptions.order(s, account.id, first, service.MONTH, BUYER)
        subscription = Subscription(
            account_id=account.id,
            profile_id=first,
            product_id=placed.product_id,
            started_on=TODAY,
            renews_on=TODAY + dt.timedelta(days=30),
        )
        s.add(subscription)
        s.flush()
        before = dict(s.get(ApplicantProfile, first).answers)

        newer = to_row(normalise({**ANSWERS, "employees": "50-249"}), account.id)
        newer.version = 2
        s.add(newer)
        s.flush()
        assert subscriptions.monitored_profile(s, subscription).id == newer.id
        assert subscription.profile_id == first  # the version it was bought with, kept
        assert s.get(ApplicantProfile, first).answers == before  # and that version untouched


@db
def test_every_invoice_line_says_what_was_bought(registry):  # noqa: F811
    from app.models import Call, Programme, SourceFeed

    with registry[0]() as s:
        account = _account(s)
        profile = _profile_id(s, account)
        report, _ = service.create(s, account.id, profile, BUYER)
        monthly, _ = subscriptions.order(s, account.id, profile, service.MONTH, BUYER)
        source = s.scalar(select(SourceFeed).where(SourceFeed.slug == "economy"))
        programme = Programme(source_feed_id=source.id, slug="t-line", name_mk="x", institution="x")
        s.add(programme)
        s.flush()
        call = Call(
            programme_id=programme.id,
            source_feed_id=source.id,
            title_mk="x",
            canonical_url="https://x",
        )
        s.add(call)
        s.flush()
        package, _ = service.create_package(s, account.id, profile, call.id, BUYER)
        assert proforma.describe(s, report).startswith("Детален извештај")
        assert proforma.describe(s, package).startswith("Пакет на документи")
        period = (dt.date(2026, 10, 16), dt.date(2026, 11, 16))
        assert proforma.describe(s, monthly, period) == (
            "Следење на нови јавни повици за профилот на барателот, еден месец, "
            "од 16.10.2026 до 16.11.2026"
        )


def test_no_plan_but_the_two():
    with pytest.raises(subscriptions.SubscriptionRefused):
        subscriptions.order(None, None, None, "monitoring-week", BUYER)
