"""Unsubscribe and consent (roadmap P6 s80).

The acceptance: "one click, no dark pattern". From the e-mail (the link, or the mail client's
own one-click button), or from the account: one button, no sign-in, no questions; every grant
and withdrawal recorded. Against PostgreSQL in a rolled-back transaction.
"""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app import create_app
from app.config import load_settings
from app.matching.normalise import normalise, to_row
from app.models import Account, ConsentRecord, Subscription
from app.orders import numbering, service, subscriptions
from app.web import account as account_web
from tests.test_account import ANSWERS
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

SECRET = "test-secret-for-the-unsubscribe-tokens-0123456789"


@pytest.fixture
def site(registry, monkeypatch, tmp_path):  # noqa: F811
    factory = registry[0]
    monkeypatch.setattr("app.web.unsubscribe._sessions", lambda: factory)
    monkeypatch.setattr(account_web, "_sessions", lambda: factory)
    app = create_app(
        load_settings(env="testing", secret_key=SECRET, outbox_dir=str(tmp_path / "o"))
    )
    return app.test_client(), factory


def _subscription(s, *, days=20) -> Subscription:
    account = Account(email=f"u-{uuid.uuid4().hex[:8]}@example.test")
    s.add(account)
    s.flush()
    row = to_row(normalise(ANSWERS), account.id)
    s.add(row)
    s.flush()
    today = numbering.today()
    subscription = Subscription(
        account_id=account.id,
        profile_id=row.id,
        product_id=service.ensure_product(s, service.MONTH).id,
        started_on=today - dt.timedelta(days=3),
        renews_on=today + dt.timedelta(days=days),
    )
    s.add(subscription)
    s.commit()
    return subscription


def _consents(s, account_id):
    return [
        c.granted
        for c in s.scalars(
            select(ConsentRecord)
            .where(ConsentRecord.account_id == account_id, ConsentRecord.purpose == "alerts")
            .order_by(ConsentRecord.id)
        )
    ]


def test_the_link_names_a_subscription_and_cannot_be_forged():
    token = subscriptions.unsubscribe_token(SECRET, "abc")
    assert subscriptions.from_token(SECRET, token) == "abc"
    assert subscriptions.from_token(SECRET, token[:-2] + "xx") is None
    assert subscriptions.from_token("another-secret-entirely-0123456789", token) is None


@db
def test_opening_the_link_changes_nothing_and_shows_one_button(site):
    client, factory = site
    with factory() as s:
        subscription = _subscription(s)
    token = subscriptions.unsubscribe_token(SECRET, subscription.id)
    page = client.get(f"/otkazi-sledenje/{token}").get_data(as_text=True)
    assert page.count("<button") == 1 and "Откажи ги известувањата" in page
    assert "не се враќа" in page  # said before, not discovered after
    with factory() as s:
        assert s.get(Subscription, subscription.id).cancelled_at is None


@db
def test_one_click_cancels_without_signing_in_and_is_recorded(site):
    client, factory = site
    with factory() as s:
        subscription = _subscription(s)
    token = subscriptions.unsubscribe_token(SECRET, subscription.id)
    done = client.post(f"/otkazi-sledenje/{token}")
    assert done.status_code == 200 and "Известувањата се откажани" in done.get_data(as_text=True)
    with factory() as s:
        assert s.get(Subscription, subscription.id).cancelled_at is not None
        assert _consents(s, subscription.account_id) == [False]


@db
def test_the_mail_clients_one_click_post_works_too(site):
    """RFC 8058: the client POSTs «List-Unsubscribe=One-Click», with no session and no token."""
    client, factory = site
    with factory() as s:
        subscription = _subscription(s)
    token = subscriptions.unsubscribe_token(SECRET, subscription.id)
    done = client.post(f"/otkazi-sledenje/{token}", data={"List-Unsubscribe": "One-Click"})
    assert done.status_code == 200
    with factory() as s:
        assert s.get(Subscription, subscription.id).cancelled_at is not None


def test_a_forged_link_is_not_found(site):
    client, _ = site
    assert client.get("/otkazi-sledenje/nonsense").status_code == 404


@db
def test_the_account_cancels_and_resumes_with_one_button_each(site, monkeypatch):
    client, factory = site
    with factory() as s:
        subscription = _subscription(s)
    monkeypatch.setattr(account_web, "current_account_id", lambda: subscription.account_id)
    with client.session_transaction() as session:
        session["csrf"] = "t"

    home = client.get("/smetka").get_data(as_text=True)
    assert "Активни до" in home and "Откажи ги известувањата" in home
    client.post("/smetka/sledenje/otkazi", data={"csrf": "t"})
    home = client.get("/smetka").get_data(as_text=True)
    assert "Откажани" in home and "Врати ги известувањата" in home
    client.post("/smetka/sledenje/prodolzi", data={"csrf": "t"})
    with factory() as s:
        assert s.get(Subscription, subscription.id).cancelled_at is None
        assert _consents(s, subscription.account_id) == [False, True]


@db
def test_a_lapsed_subscription_cannot_be_resumed(registry):  # noqa: F811
    with registry[0]() as s:
        subscription = _subscription(s, days=1)
        subscriptions.cancel(s, subscription)
        assert not subscriptions.resume(s, subscription, numbering.today() + dt.timedelta(days=2))
        assert subscription.cancelled_at is not None
