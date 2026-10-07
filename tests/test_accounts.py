"""Erasure, export and retention (app/accounts.py): the privacy policy's promises, kept.

Against PostgreSQL in a rolled-back transaction (stage 1's registry fixture).
"""

import datetime as dt
import json
import uuid

from sqlalchemy import select

from app import accounts
from app.matching.normalise import normalise, to_row
from app.models import Account, ApplicantProfile, ConsentRecord
from app.models.commerce import Order, Product
from tests.test_account import _ask, _fresh, _link, _use
from tests.test_account import site as site  # noqa: F401 (fixture)
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

ANSWERS = {
    "entity": "doo",
    "municipality": "MK00814",
    "founded": "2010",
    "employees": "10-49",
    "nace": "10.71",
    "description": "Нова печка, контакт Марија 070 123 456",
}
NOW = dt.datetime(2026, 10, 7, 12, tzinfo=dt.UTC)


def _account(s, *, seen=NOW, profiles=1) -> Account:
    account = Account(email=f"{uuid.uuid4().hex[:8]}@example.test", last_seen_at=seen)
    s.add(account)
    s.flush()
    for version in range(1, profiles + 1):
        row = to_row(normalise(ANSWERS), account.id)
        row.version = version
        s.add(row)
    s.add(
        ConsentRecord(
            account_id=account.id,
            purpose="terms",
            granted=True,
            policy_version="2026-10-07",
            ip_address="192.0.2.1",
        )
    )
    s.flush()
    return account


def _order(s, account) -> Order:
    product = Product(sku=f"report-{uuid.uuid4().hex[:6]}", name_mk="Извештај", price_mkd=8900)
    s.add(product)
    s.flush()
    profile = s.scalar(select(ApplicantProfile).where(ApplicantProfile.account_id == account.id))
    order = Order(
        account_id=account.id,
        profile_id=profile.id,
        product_id=product.id,
        amount_mkd=8900,
        vat_mkd=1602,
    )
    s.add(order)
    s.flush()
    return order


@db
def test_erasure_without_an_order_leaves_nothing_personal(registry):  # noqa: F811
    factory = registry[0]
    with factory() as s:
        account = _account(s, profiles=2)
        result = accounts.erase(s, account, NOW)
        s.flush()
        assert result == {"profiles_deleted": 2, "profiles_scrubbed": 0}
        assert account.email.endswith("@anonymised.invalid") and account.anonymised_at == NOW
        assert account.last_seen_at is None and account.email_verified_at is None
        assert (
            s.scalars(
                select(ApplicantProfile).where(ApplicantProfile.account_id == account.id)
            ).all()
            == []
        )
        consent = s.scalar(select(ConsentRecord).where(ConsentRecord.account_id == account.id))
        assert consent.ip_address is None and consent.policy_version == "2026-10-07"


@db
def test_a_profile_behind_an_order_stays_without_its_free_text(registry):  # noqa: F811
    """The tax law keeps the order; the report it bought must stay reproducible."""
    factory = registry[0]
    with factory() as s:
        account = _account(s)
        order = _order(s, account)
        result = accounts.erase(s, account, NOW)
        kept = s.get(ApplicantProfile, order.profile_id)
        assert result == {"profiles_deleted": 0, "profiles_scrubbed": 1}
        assert "description" not in kept.answers and kept.project_description is None
        assert kept.answers["nace"] == "10.71"  # the shape of the company stays


@db
def test_after_erasure_an_old_sign_in_link_no_longer_works(site):  # noqa: F811
    client, factory, outbox = site
    me = _fresh()
    _ask(client, me)
    _use(client, _link(outbox))
    _ask(client.application.test_client(), me)
    pending = _link(outbox)

    with client.session_transaction() as sess:
        token = sess.setdefault("csrf", "test-token")
    assert "Сметката е избришана" in client.post("/smetka/izbrishi", data={"csrf": token}).get_data(
        as_text=True
    )
    assert _use(client.application.test_client(), pending).status_code == 400
    with factory() as s:
        assert s.scalar(select(Account).where(Account.email == me)) is None


@db
def test_the_retention_job_forgets_profiles_after_24_months_and_keeps_the_account(registry):  # noqa: F811
    factory = registry[0]
    with factory() as s:
        quiet = _account(s, seen=NOW - dt.timedelta(days=750))
        active = _account(s, seen=NOW - dt.timedelta(days=30))
        assert [a for a, _ in accounts.anonymise_stale(s, NOW, dry_run=True)] == [quiet.id]
        accounts.anonymise_stale(s, NOW)
        remaining = {
            p.account_id
            for p in s.scalars(
                select(ApplicantProfile).where(
                    ApplicantProfile.account_id.in_([quiet.id, active.id])
                )
            )
        }
        assert remaining == {active.id}
        assert quiet.anonymised_at is None and "@example.test" in quiet.email


@db
def test_the_export_is_the_persons_own_data(site):  # noqa: F811
    client, _factory, outbox = site
    me = _fresh()
    _ask(client, me)
    _use(client, _link(outbox))
    response = client.get("/smetka/izvoz")
    assert response.mimetype == "application/json"
    assert "attachment" in response.headers["Content-Disposition"]
    data = json.loads(response.get_data(as_text=True))
    assert data["е-пошта"] == me and data["согласности"][0]["за"] == "terms"


def test_signed_out_there_is_nothing_to_export_or_erase(client):
    assert client.get("/smetka/izvoz").status_code == 302
    client.get("/najava")
    with client.session_transaction() as sess:
        token = sess["csrf"]
    assert client.post("/smetka/izbrishi", data={"csrf": token}).status_code == 302


def test_the_operator_commands_exist(app):
    result = app.test_cli_runner().invoke(args=["accounts", "--help"])
    for command in ("erase", "export", "anonymise-stale"):
        assert command in result.output


def test_the_retention_job_is_scheduled():
    from pathlib import Path

    cron = (Path(__file__).resolve().parents[1] / "ops" / "cron.d" / "grants").read_text(
        encoding="utf-8"
    )
    assert "flask accounts anonymise-stale" in cron
