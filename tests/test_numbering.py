"""Invoice numbering at the edges (roadmap P4 s54).

The acceptance: "year rollover produces no gap and no duplicate". What can go wrong at a year
end: the server's clock is UTC while the business year is Skopje's; a prefix changed in the
middle of a year; two documents numbered at once; a number whose year disagrees with its date.
Against PostgreSQL. In 2099 and 2100, which no real invoice has.
"""

import datetime as dt
import threading
import time

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import load_settings
from app.db import session_factory
from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind, OrderState
from app.orders import numbering, service
from tests.test_accounts import _account
from tests.test_orders import BUYER, _profile_id
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

PF = InvoiceKind.PROFORMA


def _clock(monkeypatch, utc: dt.datetime):
    """The server's clock reads `utc`; numbering turns it into Skopje's date itself."""
    monkeypatch.setattr(numbering, "now", lambda: utc)


# ------------------------------------------------------------------ the business date


@pytest.mark.parametrize(
    "utc, day",
    [
        (dt.datetime(2099, 12, 31, 22, 30, tzinfo=dt.UTC), dt.date(2099, 12, 31)),  # 23:30 there
        (dt.datetime(2099, 12, 31, 23, 30, tzinfo=dt.UTC), dt.date(2100, 1, 1)),  # 00:30 there
        (dt.datetime(2026, 6, 30, 22, 30, tzinfo=dt.UTC), dt.date(2026, 7, 1)),  # summer, UTC+2
    ],
)
def test_the_business_date_is_skopjes_not_the_servers(monkeypatch, utc, day):
    _clock(monkeypatch, utc)
    assert numbering.today() == day


@db
def test_an_order_on_new_years_night_belongs_wholly_to_the_new_year(registry, monkeypatch):  # noqa: F811
    _clock(monkeypatch, dt.datetime(2099, 12, 31, 23, 30, tzinfo=dt.UTC))
    with registry[0]() as s:
        account = _account(s)
        order, request = service.create(s, account.id, _profile_id(s, account), BUYER)
        proforma = s.scalar(select(Invoice).where(Invoice.order_id == order.id))
        assert request.reference.endswith("-2100-0001")
        assert proforma.fiscal_year == 2100 and proforma.issued_at == dt.date(2100, 1, 1)


@db
def test_the_last_order_of_a_year_and_the_first_of_the_next(registry, monkeypatch):  # noqa: F811
    with registry[0]() as s:
        account = _account(s)
        profile = _profile_id(s, account)
        numbers = []
        # Each round: 23:59 in Skopje, then just past its midnight (23:00 UTC in winter).
        for minute in (0, 29, 31):
            _clock(monkeypatch, dt.datetime(2099, 12, 31, 22, 59, tzinfo=dt.UTC))
            numbers.append(service.create(s, account.id, profile, BUYER)[1].reference)
            _clock(monkeypatch, dt.datetime(2099, 12, 31, 23, minute, tzinfo=dt.UTC))
            numbers.append(service.create(s, account.id, profile, BUYER)[1].reference)
        old = [n for n in numbers if "-2099-" in n]
        new = [n for n in numbers if "-2100-" in n]
        assert [n[-4:] for n in old] == ["0001", "0002", "0003"]
        assert [n[-4:] for n in new] == ["0001", "0002", "0003"]


# ------------------------------------------------------------------ one series per year


@db
def test_a_prefix_changed_in_the_middle_of_a_year_is_refused(registry, monkeypatch):  # noqa: F811
    with registry[0]() as s:
        account = _account(s)
        service.create(s, account.id, _profile_id(s, account), BUYER, today=dt.date(2099, 3, 1))
        changed = {**numbering.settings(), "prefixes": {"proforma": "PRO", "final": "Ф"}}
        monkeypatch.setattr(numbering, "settings", lambda: changed)
        with pytest.raises(numbering.NumberingError, match="prefix changed"):
            numbering.next_number(s, PF, 2099)
        assert numbering.next_number(s, PF, 2100) == "PRO-2100-0001"  # a new year may


@db
def test_the_year_on_the_paper_is_the_numbers_year(registry):  # noqa: F811
    with registry[0]() as s:
        account = _account(s)
        order, _ = service.create(
            s, account.id, _profile_id(s, account), BUYER, today=dt.date(2099, 12, 31)
        )
        proforma = s.scalar(select(Invoice).where(Invoice.order_id == order.id))
        proforma.issued_at = dt.date(2100, 1, 1)
        with pytest.raises(IntegrityError, match="ck_invoice_fiscal_year"):
            s.flush()


@db
def test_the_audit_finds_a_gap_and_is_silent_over_a_whole_series(registry):  # noqa: F811
    with registry[0]() as s:
        account = _account(s)
        profile = _profile_id(s, account)
        for _ in range(2):
            service.create(s, account.id, profile, BUYER, today=dt.date(2099, 5, 1))
        assert not [p for p in numbering.audit(s) if "2099" in p]

        order, _ = service.create(s, account.id, profile, BUYER, today=dt.date(2099, 5, 2))
        s.scalar(select(Invoice).where(Invoice.order_id == order.id)).number = "ПФ-2099-0005"
        s.flush()
        assert "proforma 2099: missing 0003, 0004" in numbering.audit(s)


# ------------------------------------------------------------------ two at once


@db
def test_two_documents_numbered_at_the_same_moment_get_two_numbers():
    """Two real connections, both committing: the second waits for the first's lock."""
    sessions = session_factory(load_settings())
    year = 2199
    with sessions() as s:
        account = _account(s)
        profile = _profile_id(s, account)
        order = Order(
            account_id=account.id,
            profile_id=profile,
            product_id=service.ensure_product(s).id,
            state=OrderState.INVOICED,
            amount_mkd=1,
            vat_mkd=0,
        )
        s.add(order)
        s.commit()
        account_id, order_id = account.id, order.id

    got, first_holds_lock = {}, threading.Event()

    def number(name, hold):
        with sessions() as s:
            n = numbering.next_number(s, PF, year)
            if hold:
                first_holds_lock.set()
                time.sleep(0.5)  # the other is now waiting on the lock, not reading
            s.add(
                Invoice(
                    order_id=order_id,
                    kind=PF,
                    number=n,
                    fiscal_year=year,
                    issued_at=dt.date(year, 1, 1),
                    amount_mkd=1,
                    vat_mkd=0,
                    total_mkd=1,
                )
            )
            s.commit()
            got[name] = n

    try:
        first = threading.Thread(target=number, args=("first", True))
        first.start()
        first_holds_lock.wait(5)
        second = threading.Thread(target=number, args=("second", False))
        second.start()
        first.join(10)
        second.join(10)
        assert sorted(got.values()) == [f"ПФ-{year}-0001", f"ПФ-{year}-0002"]
    finally:
        with sessions() as s:
            s.execute(text("DELETE FROM invoice WHERE fiscal_year = :y"), {"y": year})
            s.execute(text('DELETE FROM "order" WHERE id = :o'), {"o": order_id})
            for table in ("consent_record", "applicant_profile"):
                s.execute(text(f"DELETE FROM {table} WHERE account_id = :a"), {"a": account_id})
            s.execute(text("DELETE FROM account WHERE id = :a"), {"a": account_id})
            s.commit()


def test_nothing_in_the_order_logic_reads_the_servers_date():
    from pathlib import Path

    orders = Path(__file__).resolve().parents[1] / "app" / "orders"
    for path in orders.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "date.today()" not in source, path.name
        assert "datetime.now()" not in source, path.name
