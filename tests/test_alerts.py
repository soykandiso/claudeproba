"""New calls for subscribers (roadmap P6 s77).

The acceptance: "runs after each ingestion, not on a separate schedule": a call is matched for
every running subscription when a person publishes it. Judged by the free shortlist's own
function, against the account's newest profile; once per subscription and call. Against
PostgreSQL, on stage 1's registry (a test source, nothing else published).
"""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app import alerts
from app.matching.normalise import normalise, to_row
from app.models import Account, Alert, Subscription
from app.models.enums import Verdict
from app.orders import service
from tests import test_stage1
from tests.test_shortlist import EXCLUDES, FITS
from tests.test_stage1 import COMPANY, DATABASE_AVAILABLE, NOW, make_call

registry = test_stage1.registry
db = pytest.mark.skipif(not DATABASE_AVAILABLE, reason="no database reachable")
TODAY = NOW.date()


def _subscriber(s, *, answers=COMPANY, started=TODAY - dt.timedelta(days=3), days=30, versions=()):
    account = Account(email=f"sub-{uuid.uuid4().hex[:8]}@example.test")
    s.add(account)
    s.flush()
    first = to_row(normalise(answers, TODAY), account.id)
    s.add(first)
    s.flush()
    for n, more in enumerate(versions, 2):
        row = to_row(normalise({**answers, **more}, TODAY), account.id)
        row.version = n
        s.add(row)
    product = service.ensure_product(s, service.MONTH)
    subscription = Subscription(
        account_id=account.id,
        profile_id=first.id,
        product_id=product.id,
        started_on=started,
        renews_on=started + dt.timedelta(days=days),
    )
    s.add(subscription)
    s.flush()
    return subscription


def _alerts(s, subscription):
    return s.scalars(select(Alert).where(Alert.subscription_id == subscription.id)).all()


@db
def test_a_published_call_that_fits_alerts_once(registry):
    factory, source, snapshot = registry
    with factory() as s:
        subscription = _subscriber(s)
        call = make_call(s, source, snapshot, title="Нов повик за софтвер", criteria=[FITS])
        written = alerts.match_call(s, call.id, NOW)
        assert [a.call_id for a in written] == [call.id]
        assert written[0].verdict in alerts.ALERTED and written[0].sent_at is None
        assert written[0].profile_id == subscription.profile_id

        assert alerts.match_call(s, call.id, NOW) == []  # matched again: nothing new
        assert len(_alerts(s, subscription)) == 1


@db
def test_a_call_the_rules_exclude_or_not_yet_published_alerts_no_one(registry):
    factory, source, snapshot = registry
    with factory() as s:
        subscription = _subscriber(s)
        excluded = make_call(s, source, snapshot, title="Само за големи", criteria=[EXCLUDES])
        hidden = make_call(
            s, source, snapshot, title="Неодобрен", criteria=[FITS], is_published=False
        )
        assert alerts.match_call(s, excluded.id, NOW) == []
        assert alerts.match_call(s, hidden.id, NOW) == []
        assert _alerts(s, subscription) == []


@db
@pytest.mark.parametrize(
    "started, days",
    [(TODAY - dt.timedelta(days=40), 30), (TODAY + dt.timedelta(days=1), 30)],
    ids=["lapsed", "not-yet-started"],
)
def test_only_a_running_period_is_alerted(registry, started, days):
    factory, source, snapshot = registry
    with factory() as s:
        subscription = _subscriber(s, started=started, days=days)
        call = make_call(s, source, snapshot, criteria=[FITS])
        assert alerts.match_call(s, call.id, NOW) == []
        assert _alerts(s, subscription) == []


@db
def test_a_cancelled_subscription_is_alerted_until_its_paid_end(registry):
    factory, source, snapshot = registry
    with factory() as s:
        subscription = _subscriber(s)
        subscription.cancelled_at = NOW
        call = make_call(s, source, snapshot, criteria=[FITS])
        assert len(alerts.match_call(s, call.id, NOW)) == 1


@db
def test_the_newest_profile_decides(registry):
    """Version 1 is a software company the call is for; version 2 is a bakery: no alert."""
    factory, source, snapshot = registry
    with factory() as s:
        subscription = _subscriber(s, versions=[{"nace": "10.71"}])
        call = make_call(s, source, snapshot, criteria=[FITS])  # activity 62.*
        assert alerts.match_call(s, call.id, NOW) == []
        newest = alerts.subscriptions.monitored_profile(s, subscription)
        assert newest.version == 2 and newest.id != subscription.profile_id

        # Back to software in version 3: the next call is alerted, with the version it matched.
        third = to_row(normalise(COMPANY, TODAY), subscription.account_id)
        third.version = 3
        s.add(third)
        s.flush()
        later = make_call(s, source, snapshot, title="Следен повик", criteria=[FITS])
        written = alerts.match_call(s, later.id, NOW)
        assert [a.profile_id for a in written] == [third.id]


@db
def test_a_failed_match_never_undoes_the_publication(registry, monkeypatch):
    factory, *_ = registry

    def broken(session, call_id, now=None):
        raise RuntimeError("the shortlist broke")

    monkeypatch.setattr(alerts, "match_call", broken)
    assert alerts.after_publish(factory, uuid.uuid4()) is None


def test_every_verdict_but_not_eligible_is_alerted():
    assert set(Verdict) - {Verdict.NOT_ELIGIBLE} == alerts.ALERTED


@db
def test_the_catch_up_finds_each_call_approved_since_a_day_once(registry):
    from app.models import ReviewQueueItem
    from app.models.enums import ReviewKind, ReviewState

    factory, source, snapshot = registry
    with factory() as s:
        call = make_call(s, source, snapshot, criteria=[FITS])
        old = make_call(s, source, snapshot, title="Стар", criteria=[FITS])
        for which, when in ((call, NOW), (call, NOW), (old, NOW - dt.timedelta(days=30))):
            s.add(
                ReviewQueueItem(
                    kind=ReviewKind.EXTRACTION,
                    state=ReviewState.APPROVED,
                    call_id=which.id,
                    reason="test",
                    resolved_at=when,
                )
            )
        s.flush()
        assert alerts.published_since(s, NOW - dt.timedelta(days=1)) == [call.id]
