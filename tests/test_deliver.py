"""Delivering a paid report (roadmap P4 s53).

The acceptance: "reviewed PDF emailed, order state machine complete". A report approved for
a paid order goes to its buyer with the invoice; when anything fails nothing is sent, no
invoice number is spent and the order waits. Against PostgreSQL, on the report tests' world
(one call, one verified run), with mail written to a temporary outbox.
"""

import datetime as dt
import email
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import create_app
from app.config import load_settings
from app.ingestion.snapshots import SnapshotStore
from app.models import Account, MatchRun, ReviewQueueItem
from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind, OrderState
from app.orders import deliver, fulfil, reconcile, service
from app.review import report as reports
from tests import test_report_compose as tc
from tests.test_orders import BUYER
from tests.test_report_render import needs_db
from tests.test_stage1 import NOW

registry = tc.registry
world = tc.world

ORDERED = dt.date(2026, 9, 23)
PAID = dt.date(2026, 9, 24)
SENT = dt.datetime(2026, 9, 30, 10, 0, tzinfo=dt.UTC)  # before the world's call closes


def _paid_order(world, *, approve=True):
    """A paid order whose analysis ran and whose report is approved (or waiting)."""
    factory, run_id = tc.verified_run(world)
    item, _ = tc.composed(factory, run_id, tc.prose())
    with factory() as s:
        if approve:
            reports.approve(s, s.get(ReviewQueueItem, item.id), note="во ред", now=NOW)
        account = Account(email=f"kupuvach-{uuid.uuid4().hex[:8]}@example.test")
        s.add(account)
        s.flush()
        profile_id = s.get(MatchRun, run_id).profile_id
        order, _ = service.create(s, account.id, profile_id, BUYER, today=ORDERED)
        paid = s.scalar(select(Invoice).where(Invoice.order_id == order.id))
        reconcile.confirm(s, paid.id, Decimal(paid.total_mkd), "NLB 7", PAID)
        assert fulfil.begin(s, order.id) == profile_id
        fulfil.link(s, order.id, run_id)
        return factory, order.id, item.id


@pytest.fixture
def sending(tmp_path):
    settings = load_settings(env="testing", outbox_dir=str(tmp_path / "outbox"))
    return settings, SnapshotStore(tmp_path / "store"), tmp_path / "outbox"


def _deliver(factory, sending, order_id):
    settings, store, _ = sending
    with factory() as s:
        return deliver.deliver(s, store, settings, order_id, link="http://x/naracka", now=SENT)


@needs_db
def test_the_report_and_its_invoice_reach_the_buyer_and_the_order_is_delivered(world, sending):
    factory, order_id, _ = _paid_order(world)
    _, store, outbox = sending
    done = _deliver(factory, sending, order_id)

    with factory() as s:
        order = s.get(Order, order_id)
        final = s.scalar(
            select(Invoice).where(Invoice.order_id == order_id, Invoice.kind == InvoiceKind.FINAL)
        )
        assert order.state == OrderState.DELIVERED and order.delivered_at == SENT
        assert final.number == done.invoice_number and final.number.startswith("Ф-2026-")
        assert final.issued_at == SENT.date() and final.paid_at.date() == PAID
        assert final.bank_reference == "NLB 7"
        kept_report = store.get(order.report_storage_key)
        kept_invoice = store.get(final.pdf_storage_key)

    message = email.message_from_bytes(next(outbox.glob("*.eml")).read_bytes())
    attached = [
        p.get_payload(decode=True)
        for p in message.walk()
        if p.get_content_type() == "application/pdf"
    ]
    assert attached == [kept_report, kept_invoice]  # what is kept is exactly what was sent
    body = next(p for p in message.walk() if p.get_content_type() == "text/plain")
    text = body.get_payload(decode=True).decode()
    assert final.number in text and "последната верзија" in text
    for banned in ("гарантира", "ќе добиете"):
        assert banned not in text.lower()


@needs_db
def test_a_failed_mail_sends_nothing_spends_no_number_and_the_order_waits(world, sending):
    factory, order_id, _ = _paid_order(world)
    _, store, _ = sending
    production_without_mail = load_settings(env="testing", mail_backend="smtp", smtp_host=None)
    with factory() as s:
        before = s.scalar(
            select(func.count()).select_from(Invoice).where(Invoice.kind == InvoiceKind.FINAL)
        )
        with pytest.raises(deliver.Refused, match="Е-поштата не замина"):
            deliver.deliver(s, store, production_without_mail, order_id, link="x", now=SENT)
    with factory() as s:
        order = s.get(Order, order_id)
        assert order.state == OrderState.IN_PROGRESS and order.report_storage_key is None
        after = s.scalar(
            select(func.count()).select_from(Invoice).where(Invoice.kind == InvoiceKind.FINAL)
        )
        assert after == before

    # Sent again once mail works: delivered, with the number the failure did not take.
    assert _deliver(factory, sending, order_id).invoice_number.startswith("Ф-2026-")


@needs_db
def test_nothing_is_sent_before_a_person_approves(world, sending):
    factory, order_id, _ = _paid_order(world, approve=False)
    with pytest.raises(deliver.Refused, match="уште не е прифатен"):
        _deliver(factory, sending, order_id)


@needs_db
def test_a_report_is_delivered_once(world, sending):
    factory, order_id, _ = _paid_order(world)
    _deliver(factory, sending, order_id)
    with pytest.raises(deliver.Refused, match="веќе испорачана"):
        _deliver(factory, sending, order_id)


@needs_db
def test_a_report_whose_call_closed_since_approval_is_not_sent(world, sending):
    factory, order_id, _ = _paid_order(world)
    settings, store, outbox = sending
    late = dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
    with factory() as s, pytest.raises(deliver.Refused, match="не може да се отпечати"):
        deliver.deliver(s, store, settings, order_id, link="x", now=late)
    assert not list(outbox.glob("*.eml"))


@needs_db
def test_a_delivered_order_has_its_report_on_file_by_constraint(world):
    from sqlalchemy.exc import IntegrityError

    factory, order_id, _ = _paid_order(world)
    with factory() as s:
        order = s.get(Order, order_id)
        order.state, order.delivered_at = OrderState.DELIVERED, SENT
        with pytest.raises(IntegrityError, match="delivered_has_report"):
            s.flush()


# ------------------------------------------------------------------ the screens


@pytest.fixture
def site(world, sending, monkeypatch):
    factory = world[0]
    settings, store, _ = sending
    monkeypatch.setattr("app.web.admin._sessions", lambda: factory)
    monkeypatch.setattr("app.web.admin._store", lambda: store)
    monkeypatch.setattr("app.web.checkout._sessions", lambda: factory)
    app = create_app(settings.model_copy(update={"snapshot_dir": str(store.root)}))
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = "test-token"
    return client


@needs_db
def test_approving_a_paid_orders_report_sends_it(world, site, monkeypatch):
    factory, order_id, item_id = _paid_order(world, approve=False)
    monkeypatch.setattr("app.orders.deliver.dt", _Frozen)
    page = site.get(f"/admin/izveshtaj/{item_id}").get_data(as_text=True)
    assert "Прифаќањето го испраќа извештајот на купувачот веднаш" in page

    done = site.post(
        f"/admin/izveshtaj/{item_id}/odobri", data={"csrf": "test-token"}, follow_redirects=True
    )
    assert "Извештајот е испратен на kupuvach-" in done.get_data(as_text=True)
    with factory() as s:
        assert s.get(Order, order_id).state == OrderState.DELIVERED


@needs_db
def test_the_buyer_downloads_exactly_what_was_sent(world, site, sending, monkeypatch):
    factory, order_id, _ = _paid_order(world)
    _deliver(factory, sending, order_id)
    with factory() as s:
        account_id = s.get(Order, order_id).account_id
    monkeypatch.setattr("app.web.account.current_account_id", lambda: account_id)

    page = site.get(f"/naracka/{order_id}").get_data(as_text=True)
    assert "Испорачана" in page and "30.09.2026" in page
    report = site.get(f"/naracka/{order_id}/izveshtaj.pdf")
    invoice = site.get(f"/naracka/{order_id}/faktura.pdf")
    _, store, _ = sending
    with factory() as s:
        order = s.get(Order, order_id)
        assert report.data == store.get(order.report_storage_key)
    assert invoice.status_code == 200 and invoice.data.startswith(b"%PDF")
    assert "%D0%A4-2026-" in invoice.headers["Content-Disposition"]  # Ф-2026-…


class _Frozen:
    """`dt` for app.orders.deliver, with now() at SENT: the world's call is still open."""

    date, time, timedelta, UTC = dt.date, dt.time, dt.timedelta, dt.UTC

    class datetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return SENT if tz else SENT.replace(tzinfo=None)
