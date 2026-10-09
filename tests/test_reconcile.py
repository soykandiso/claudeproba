"""Reconciling a bank transfer to a proforma (roadmap P4 s51).

The acceptance: "two-click reconciliation from a bank statement line". Find, then confirm;
nothing is marked paid on a guess. Against PostgreSQL in a rolled-back transaction (stage 1's
registry fixture), in the year 2099 so no real proforma is in the way.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import create_app
from app.config import load_settings
from app.models.commerce import Invoice
from app.models.enums import OrderState
from app.orders import reconcile, service
from tests.test_accounts import _account
from tests.test_orders import BUYER, YEAR, _profile_id
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

TODAY = dt.date.today()

# ------------------------------------------------------------------ reading a statement line


@pytest.mark.parametrize(
    "line, numbers",
    [
        ("Уплата по профактура ПФ-2026-0001", ["ПФ-2026-0001"]),
        ("PF-2026-0001 izvestaj", ["ПФ-2026-0001"]),  # the bank's Latin
        ("pf 2026 12 и ПФ/2026/0012", ["ПФ-2026-0012"]),  # the dashes lost, said twice
        ("ПФ-2025-0003; ПФ-2026-0004", ["ПФ-2025-0003", "ПФ-2026-0004"]),
        ("Фактура Ф-2026-0001", []),  # a final invoice is not a proforma
        ("уплата 5.782,00 МКД", []),
        ("SPF-2026-0001", []),  # inside another word
    ],
)
def test_proforma_numbers_are_read_as_banks_write_them(line, numbers):
    assert reconcile.numbers_in(line) == numbers


@pytest.mark.parametrize(
    "line, amount",
    [
        ("Износ 5.782,00 МКД", "5782.00"),
        ("5782,00", "5782.00"),
        ("5,782.00", "5782.00"),
        ("5 782,00", "5782.00"),
        ("5782 МКД", "5782.00"),
        ("10.502,00 ден", "10502.00"),
    ],
)
def test_amounts_are_read_either_way_round(line, amount):
    assert Decimal(amount) in reconcile.amounts_in(line)


def test_a_typed_amount_is_one_number_or_nothing():
    assert reconcile.amount("5.782,00") == Decimal("5782.00")
    assert reconcile.amount(" 5782 ") == Decimal("5782.00")
    assert reconcile.amount("") is None and reconcile.amount("пет илјади") is None
    assert reconcile.amount("-5782") is None


def test_the_year_of_a_number_is_not_an_amount():
    assert reconcile.amounts_in("ПФ-2026-0001") == []


# ------------------------------------------------------------------ against the database


def _ordered(s):
    account = _account(s)
    order, request = service.create(s, account.id, _profile_id(s, account), BUYER, today=YEAR)
    invoice = s.scalar(select(Invoice).where(Invoice.order_id == order.id))
    return order, invoice


@db
def test_a_line_finds_its_open_proforma_and_whether_the_amount_is_its(registry):  # noqa: F811
    with registry[0]() as s:
        order, invoice = _ordered(s)
        total = Decimal(invoice.total_mkd)
        found, closed = reconcile.match(s, f"Плаќање {invoice.number}, {total:.2f} МКД")
        assert [m.open.invoice.id for m in found] == [invoice.id] and found[0].amount_matches
        found, _ = reconcile.match(s, f"{invoice.number}, 100,00")
        assert not found[0].amount_matches
        assert reconcile.match(s, "ПФ-2099-9999")[1] == ["ПФ-2099-9999"]
        assert invoice.id in {o.invoice.id for o in reconcile.open_proformas(s)}


@db
def test_confirming_marks_the_proforma_and_the_order_paid(registry):  # noqa: F811
    with registry[0]() as s:
        order, invoice = _ordered(s)
        reconcile.confirm(s, invoice.id, Decimal(invoice.total_mkd), "NLB 123/09", TODAY)
        assert order.state == OrderState.PAID
        assert invoice.bank_reference == "NLB 123/09" and invoice.paid_at.date() == TODAY
        assert invoice.id not in {o.invoice.id for o in reconcile.open_proformas(s)}
        assert reconcile.recently_paid(s)[0].invoice.id == invoice.id

        with pytest.raises(reconcile.Refused, match="веќе"):
            reconcile.confirm(s, invoice.id, Decimal(invoice.total_mkd), "again", TODAY)
        assert reconcile.match(s, invoice.number)[1] == [invoice.number]


@db
@pytest.mark.parametrize(
    "change, why",
    [
        ({"paid": Decimal("100.00")}, "Делумна"),
        ({"paid": None}, "износ"),
        ({"reference": "  "}, "референцата"),
        ({"on": TODAY + dt.timedelta(days=1)}, "иднина"),
    ],
)
def test_nothing_is_marked_paid_on_a_guess(registry, change, why):  # noqa: F811
    with registry[0]() as s:
        order, invoice = _ordered(s)
        args = {"paid": Decimal(invoice.total_mkd), "reference": "ref", "on": TODAY, **change}
        with pytest.raises(reconcile.Refused, match=why):
            reconcile.confirm(s, invoice.id, **args)
        assert order.state == OrderState.INVOICED and invoice.paid_at is None


@db
def test_a_cancelled_order_is_not_paid(registry):  # noqa: F811
    with registry[0]() as s:
        order, invoice = _ordered(s)
        service.cancel(s, order)
        with pytest.raises(reconcile.Refused, match="не чека уплата"):
            reconcile.confirm(s, invoice.id, Decimal(invoice.total_mkd), "ref", TODAY)
        assert reconcile.match(s, invoice.number)[0] == []


# ------------------------------------------------------------------ the screen: two clicks


@pytest.fixture
def admin(registry, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.web.admin._sessions", lambda: registry[0])
    client = create_app(load_settings(env="testing")).test_client()
    with client.session_transaction() as session:
        session["csrf"] = "test-token"
    return client, registry[0]


@db
def test_two_clicks_from_a_statement_line(admin):
    client, factory = admin
    with factory() as s:
        order, invoice = _ordered(s)
        s.commit()
        number, total, invoice_id = invoice.number, Decimal(invoice.total_mkd), invoice.id
    line = f"ИЗМИСЛЕНА ДОО, профактура {number}, {total:.2f} МКД, реф. 0042"

    # Click one: find.
    found = client.get("/admin/uplati", query_string={"line": line}).get_data(as_text=True)
    assert "се совпаѓа" in found and f'value="{total:.2f}"' in found

    # Click two: confirm, with the form as the page filled it.
    done = client.post(
        f"/admin/uplati/{invoice_id}",
        data={
            "csrf": "test-token",
            "line": line,
            "amount": f"{total:.2f}",
            "reference": line,
            "date": TODAY.strftime("%d.%m.%Y"),
        },
    )
    assert done.status_code == 302
    page = client.get(done.location).get_data(as_text=True)
    assert f"Профактурата {number} е платена" in page and "Последни уплати" in page
    with factory() as s:
        assert s.get(Invoice, invoice_id).paid_at is not None


@db
def test_a_refusal_says_why_and_keeps_what_was_typed(admin):
    client, factory = admin
    with factory() as s:
        order, invoice = _ordered(s)
        s.commit()
        number, invoice_id = invoice.number, invoice.id
    refused = client.post(
        f"/admin/uplati/{invoice_id}",
        data={
            "csrf": "test-token",
            "line": number,
            "amount": "100",
            "reference": "r",
            "date": "9.10",
        },
    )
    assert refused.status_code == 422
    assert "дд.мм.гггг" in refused.get_data(as_text=True)
    refused = client.post(
        f"/admin/uplati/{invoice_id}",
        data={
            "csrf": "test-token",
            "line": number,
            "amount": "100",
            "reference": "r",
            "date": TODAY.strftime("%d.%m.%Y"),
        },
    )
    body = refused.get_data(as_text=True)
    assert refused.status_code == 422 and "Делумна" in body and 'value="100"' in body
    with factory() as s:
        assert s.get(Invoice, invoice_id).paid_at is None
