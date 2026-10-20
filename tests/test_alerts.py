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
def test_a_cancelled_subscription_is_alerted_no_more(registry):
    """Cancelling is asking us to stop writing (P6 s80): no alert, though the period is paid."""
    factory, source, snapshot = registry
    with factory() as s:
        subscription = _subscriber(s)
        subscription.cancelled_at = NOW
        call = make_call(s, source, snapshot, criteria=[FITS])
        assert alerts.match_call(s, call.id, NOW) == []


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


# ------------------------------------------------------------------ sending (P6 s78)


@pytest.fixture
def mailing(tmp_path):
    from app import create_app
    from app.config import load_settings

    app = create_app(load_settings(env="testing", outbox_dir=str(tmp_path / "outbox")))
    return app, tmp_path / "outbox"


def _body(outbox):
    import email

    files = sorted(outbox.glob("*.eml"))
    message = email.message_from_bytes(files[-1].read_bytes())
    subject = str(email.header.make_header(email.header.decode_header(message["Subject"])))
    return subject, message.get_payload(decode=True).decode(), len(files)


@db
def test_an_alert_is_mailed_with_its_verdict_and_every_condition_quoted(registry, mailing):
    app, outbox = mailing
    factory, source, snapshot = registry
    with factory() as s:
        subscription = _subscriber(s)
        call = make_call(s, source, snapshot, title="Нов повик за софтвер", criteria=[FITS])
        alerts.match_call(s, call.id, NOW)
        counts = alerts.send_pending(app, s, NOW)
        assert counts == {"mailed": 1, "alerts": 1, "skipped": 0, "failed": 0, "waiting": 0}
        sent = _alerts(s, subscription)[0]
        assert sent.sent_at == NOW and subscription.last_alert_at == NOW

        subject, body, files = _body(outbox)
        assert subject == "Нов повик за вашиот профил: Нов повик за софтвер"
        assert "Оценка: " in body and "„цитат“" in body  # the stored words, verbatim
        assert "http://localhost:8080/povici/izvor/" in body  # the passage behind the quote
        assert "Последна проверка на повикот:" in body and "одлуката за секоја пријава" in body

        # Sent once: a second run mails nothing.
        assert alerts.send_pending(app, s, NOW)["mailed"] == 0
        assert _body(outbox)[2] == files


@db
def test_a_call_closed_or_unpublished_by_sending_time_is_skipped_with_the_reason(registry, mailing):
    app, outbox = mailing
    factory, source, snapshot = registry
    with factory() as s:
        subscription = _subscriber(s)
        closing = make_call(s, source, snapshot, title="Се затвора", criteria=[FITS])
        hidden = make_call(s, source, snapshot, title="Ќе се повлече", criteria=[FITS])
        alerts.match_call(s, closing.id, NOW)
        alerts.match_call(s, hidden.id, NOW)
        closing.deadline_at = NOW - dt.timedelta(hours=1)
        hidden.is_published = False
        s.flush()
        assert alerts.send_pending(app, s, NOW)["skipped"] == 2
        reasons = sorted(a.skipped_reason for a in _alerts(s, subscription))
        assert reasons == ["повикот не е објавен", "рокот на повикот истече"]
        assert not outbox.exists() or not list(outbox.glob("*.eml"))


@db
def test_several_new_calls_are_one_message(registry, mailing):
    app, outbox = mailing
    factory, source, snapshot = registry
    with factory() as s:
        _subscriber(s)
        for n in range(3):
            alerts.match_call(
                s, make_call(s, source, snapshot, title=f"Повик {n}", criteria=[FITS]).id, NOW
            )
        assert alerts.send_pending(app, s, NOW)["mailed"] == 1
        subject, body, files = _body(outbox)
        assert files == 1 and subject == "3 нови повици за вашиот профил"
        assert "1. Повик" in body and "3. Повик" in body


@db
def test_an_institutions_own_words_never_stop_an_alert(registry, mailing):
    """«гарантирано» in a call's title is the institution's, quoted; our lint reads our words."""
    app, outbox = mailing
    factory, source, snapshot = registry
    with factory() as s:
        _subscriber(s)
        call = make_call(
            s, source, snapshot, title="Гарантирано финансирање за ИТ", criteria=[FITS]
        )
        alerts.match_call(s, call.id, NOW)
        assert alerts.send_pending(app, s, NOW)["mailed"] == 1


def test_production_never_mails_links_to_localhost():
    from types import SimpleNamespace

    app = SimpleNamespace(
        extensions={
            "settings": SimpleNamespace(is_production=True, public_url="http://localhost:8080")
        }
    )
    with pytest.raises(alerts.SendingRefused):
        alerts.send_pending(app, None)


# ------------------------------------------------------------------ digests (P6 s81)


@db
def test_a_burst_is_one_message_the_strongest_in_full_the_rest_listed(registry, mailing):
    app, outbox = mailing
    factory, source, snapshot = registry
    with factory() as s:
        _subscriber(s)
        for n in range(8):
            deadline = NOW + dt.timedelta(days=20 + n)
            call = make_call(
                s, source, snapshot, title=f"Повик {n}", criteria=[FITS], deadline_at=deadline
            )
            alerts.match_call(s, call.id, NOW)
        counts = alerts.send_pending(app, s, NOW)
        assert counts["mailed"] == 1 and counts["alerts"] == 8
        subject, body, files = _body(outbox)
        assert files == 1 and subject == "8 нови повици за вашиот профил"
        assert body.count("Услови, со цитат од текстот на повикот:") == alerts.DETAILED_CALLS
        assert "Уште 3 повици" in body
        # The nearest deadline first: «Повик 0» leads, «Повик 7» is only listed.
        assert body.index("1. Повик 0") < body.index("- Повик 7")


@db
def test_one_message_a_day_and_the_rest_waits_for_tomorrow(registry, mailing):
    app, outbox = mailing
    factory, source, snapshot = registry
    with factory() as s:
        subscription = _subscriber(s)
        alerts.match_call(
            s, make_call(s, source, snapshot, title="Утрински", criteria=[FITS]).id, NOW
        )
        alerts.send_pending(app, s, NOW)
        alerts.match_call(
            s, make_call(s, source, snapshot, title="Попладневен", criteria=[FITS]).id, NOW
        )
        later = alerts.send_pending(app, s, NOW + dt.timedelta(hours=3))
        assert later["mailed"] == 0 and later["waiting"] == 1
        tomorrow = alerts.send_pending(app, s, NOW + dt.timedelta(hours=21))
        assert tomorrow["mailed"] == 1
        assert all(a.sent_at for a in _alerts(s, subscription))
        assert _body(outbox)[2] == 2


@db
def test_a_quiet_month_earns_one_still_watching_note(registry, mailing):
    app, outbox = mailing
    factory, *_ = registry
    with factory() as s:
        subscription = _subscriber(s, started=TODAY - dt.timedelta(days=40), days=60)
        assert alerts.send_quiet(app, s, NOW) == 1
        subject, body, _ = _body(outbox)
        assert subject == "Ги следиме повиците за вашиот профил"
        assert "ниту еден не одговара" in body or "немаше нови повици" in body
        assert "/profil/" in body and "/otkazi-sledenje/" in body
        assert subscription.last_alert_at == NOW
        assert alerts.send_quiet(app, s, NOW + dt.timedelta(days=5)) == 0  # not again so soon


@db
def test_no_quiet_note_for_a_new_subscription_or_one_with_alerts_waiting(registry, mailing):
    app, _ = mailing
    factory, source, snapshot = registry
    with factory() as s:
        _subscriber(s, started=TODAY - dt.timedelta(days=10))  # new: not quiet yet
        waiting = _subscriber(s, started=TODAY - dt.timedelta(days=40), days=60)
        alerts.match_call(s, make_call(s, source, snapshot, criteria=[FITS]).id, NOW)
        assert _alerts(s, waiting)  # an alert is waiting: not quiet
        assert alerts.send_quiet(app, s, NOW) == 0
