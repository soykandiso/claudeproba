"""A paid order to the analysis worker, and the customer told (roadmap P4 s52).

The acceptance: "paid order enqueues analysis; customer is told what happens and when". Redis
is replaced by a recording queue (no Redis on the development machine, and none needed to
test what is handed over). Against PostgreSQL in a rolled-back transaction.
"""

import datetime as dt
import email
import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from rq.exceptions import NoSuchJobError

from app import create_app
from app.config import load_settings
from app.models import MatchRun
from app.models.enums import OrderState
from app.orders import fulfil, reconcile
from app.pricing import prices
from tests.test_reconcile import _ordered
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

TODAY = dt.date.today()
TERMS = Path(__file__).resolve().parents[1] / "app/web/templates/legal/terms/2026-10-07.html"


class Recording:
    """A queue that remembers what it was given, and the jobs it already holds."""

    connection = None

    def __init__(self, held=None):
        self.given, self.held = [], dict(held or {})

    def enqueue(self, fn, order_id, *, job_id, **_):
        self.given.append((fn, order_id, job_id))


class Held:
    def __init__(self, status):
        self.status, self.deleted = status, False

    def get_status(self):
        return self.status

    def delete(self):
        self.deleted = True


@pytest.fixture
def queue(monkeypatch):
    q = Recording()

    def fetch(job_id, connection=None):
        if job_id not in q.held:
            raise NoSuchJobError(job_id)
        return q.held[job_id]

    monkeypatch.setattr(fulfil, "_queue", lambda settings: q)
    monkeypatch.setattr("rq.job.Job.fetch", fetch)
    return q


def _paid(s):
    order, invoice = _ordered(s)
    reconcile.confirm(s, invoice.id, Decimal(invoice.total_mkd), "ref", TODAY)
    return order, invoice


# ------------------------------------------------------------------ handing over


def test_an_order_is_handed_over_once_under_its_own_id(queue):
    order_id = uuid.uuid4()
    assert fulfil.enqueue(None, order_id)
    assert queue.given == [(fulfil.job, str(order_id), f"order-{order_id}")]

    queue.held[f"order-{order_id}"] = Held("queued")
    assert not fulfil.enqueue(None, order_id)  # the sweep, a minute later
    assert len(queue.given) == 1


@pytest.mark.parametrize("status", ["failed", "finished"])
def test_a_job_that_ended_is_not_run_again_unless_the_operator_asks(queue, status):
    order_id = uuid.uuid4()
    held = queue.held[f"order-{order_id}"] = Held(status)
    assert not fulfil.enqueue(None, order_id)
    assert fulfil.enqueue(None, order_id, again=True) and held.deleted


def test_asking_again_never_doubles_a_running_job(queue):
    order_id = uuid.uuid4()
    queue.held[f"order-{order_id}"] = Held("started")
    assert not fulfil.enqueue(None, order_id, again=True)
    assert queue.given == []


def test_a_payment_stands_when_the_worker_cannot_be_reached(monkeypatch):
    def down(settings):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fulfil, "_queue", down)
    assert fulfil.after_payment(None, uuid.uuid4()) is False


@db
def test_the_sweep_hands_over_every_paid_order_not_started(registry, queue):  # noqa: F811
    with registry[0]() as s:
        paid, _ = _paid(s)
        unpaid, _ = _ordered(s)
        assert paid.id in fulfil.waiting(s) and unpaid.id not in fulfil.waiting(s)
        fulfil.dispatch(None, s)
        assert str(paid.id) in {order_id for _, order_id, _ in queue.given}
        assert str(unpaid.id) not in {order_id for _, order_id, _ in queue.given}


# ------------------------------------------------------------------ the job


@db
def test_the_job_moves_the_order_on_and_records_its_run(registry, monkeypatch):  # noqa: F811
    factory = registry[0]
    with factory() as s:
        order, _ = _paid(s)
        s.commit()
        order_id, profile_id = order.id, order.profile_id
    ran = []

    def deep_job(profile):
        ran.append(profile)
        with factory() as s:
            run = MatchRun(
                profile_id=profile, ruleset_version="t", weights_version="t", stage_reached=3
            )
            s.add(run)
            s.commit()
            return {"match_run_id": str(run.id), "calls": 5, "review_item_id": 1}

    monkeypatch.setattr("app.db.session_factory", lambda settings: factory)
    monkeypatch.setattr("app.matching.deep.job", deep_job)

    assert fulfil.job(str(order_id))["calls"] == 5
    assert ran == [str(profile_id)]
    with factory() as s:
        from app.models.commerce import Order

        done = s.get(Order, order_id)
        assert done.state == OrderState.IN_PROGRESS and done.match_run_id is not None

    # Run again (a stray job): the order has its run, nothing is analysed twice.
    assert fulfil.job(str(order_id))["skipped"] and len(ran) == 1


@db
def test_an_unpaid_or_cancelled_order_is_never_analysed(registry):  # noqa: F811
    with registry[0]() as s:
        order, _ = _ordered(s)
        assert fulfil.begin(s, order.id) is None and order.state == OrderState.INVOICED


@db
def test_a_failed_run_can_be_retried_and_only_then(registry):  # noqa: F811
    with registry[0]() as s:
        order, _ = _paid(s)
        assert fulfil.begin(s, order.id) == order.profile_id  # the job starts, then dies
        assert order.state == OrderState.IN_PROGRESS
        assert fulfil.begin(s, order.id) == order.profile_id  # the operator's retry
        assert order.id not in fulfil.waiting(s)  # the sweep leaves it alone


# ------------------------------------------------------------------ what the customer is told


@pytest.fixture
def admin(registry, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr("app.web.admin._sessions", lambda: registry[0])
    client = create_app(
        load_settings(env="testing", outbox_dir=str(tmp_path / "outbox"))
    ).test_client()
    with client.session_transaction() as session:
        session["csrf"] = "test-token"
    return client, registry[0], tmp_path / "outbox"


def _confirm(client, invoice):
    return client.post(
        f"/admin/uplati/{invoice.id}",
        data={
            "csrf": "test-token",
            "line": invoice.number,
            "amount": f"{Decimal(invoice.total_mkd):.2f}",
            "reference": "NLB 1",
            "date": TODAY.strftime("%d.%m.%Y"),
        },
        follow_redirects=True,
    )


@db
def test_marking_paid_tells_the_customer_and_hands_the_order_over(admin, queue):
    client, factory, outbox = admin
    with factory() as s:
        order, invoice = _ordered(s)
        s.commit()
    page = _confirm(client, invoice).get_data(as_text=True)
    assert "Купувачот е известен" in page and "предадена на работникот" in page
    assert [order_id for _, order_id, _ in queue.given] == [str(order.id)]

    message = email.message_from_bytes(next(outbox.glob("*.eml")).read_bytes())
    body = message.get_payload(decode=True).decode()
    days = prices().report.delivery_working_days
    assert f"во рок од {days} работни дена" in body and invoice.number in body
    assert re.search(r"http://localhost/naracka/[0-9a-f-]{36}", body)
    for banned in ("гарантира", "ќе добиете"):
        assert banned not in body.lower()


@db
def test_the_operator_is_told_when_the_worker_did_not_answer(admin, monkeypatch):
    client, factory, _ = admin

    def down(settings):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fulfil, "_queue", down)
    with factory() as s:
        _, invoice = _ordered(s)
        s.commit()
    page = _confirm(client, invoice).get_data(as_text=True)
    assert "flask orders dispatch" in page
    with factory() as s:
        assert reconcile.match(s, invoice.number)[1] == [invoice.number]  # paid all the same


def test_the_terms_promise_what_the_prices_file_says():
    words = {3: "три", 5: "пет", 7: "седум", 10: "десет"}
    days = prices().report.delivery_working_days
    assert f"во рок од {words[days]} работни дена од уплатата" in TERMS.read_text(encoding="utf-8")
