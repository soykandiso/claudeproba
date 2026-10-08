"""Orders and payment (roadmap P4 s48).

The acceptance: "a card gateway could be added later without touching order logic"
(brief §3.2). `test_a_card_gateway_plugs_in_without_touching_the_order_logic` adds one.
Against PostgreSQL in a rolled-back transaction (stage 1's registry fixture).
"""

import datetime as dt
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.commerce import Invoice
from app.models.enums import InvoiceKind, OrderState
from app.orders import numbering, providers, service, states
from app.orders.providers import Evidence, PaymentRequest
from tests.test_accounts import _account
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

# A year no real invoice has, so the numbering starts from nothing.
YEAR = dt.date(2099, 3, 1)
BUYER = service.Buyer(name="Измислена ДОО", address="Измислена 1, Битола", edb="4000000000000")


def _profile_id(s, account):
    from app.models import ApplicantProfile

    return s.scalar(select(ApplicantProfile.id).where(ApplicantProfile.account_id == account.id))


# ------------------------------------------------------------------ the state machine


@pytest.mark.parametrize(
    "start,to",
    [
        (OrderState.CREATED, OrderState.INVOICED),
        (OrderState.INVOICED, OrderState.PAID),
        (OrderState.PAID, OrderState.IN_PROGRESS),
        (OrderState.IN_PROGRESS, OrderState.DELIVERED),
        (OrderState.INVOICED, OrderState.CANCELLED),
        (OrderState.DELIVERED, OrderState.REFUNDED),
    ],
)
def test_the_business_paths_are_allowed(start, to):
    order = type("O", (), {"id": "x", "state": start})()
    states.move(order, to)
    assert order.state == to


@pytest.mark.parametrize(
    "start,to",
    [
        (OrderState.CREATED, OrderState.PAID),  # never paid without being billed
        (OrderState.INVOICED, OrderState.DELIVERED),  # never delivered without payment
        (OrderState.PAID, OrderState.CANCELLED),  # after payment, a refund, not a cancel
        (OrderState.CANCELLED, OrderState.INVOICED),
        (OrderState.REFUNDED, OrderState.PAID),
    ],
)
def test_anything_else_is_refused(start, to):
    order = type("O", (), {"id": "x", "state": start})()
    with pytest.raises(states.IllegalTransition):
        states.move(order, to)


# ------------------------------------------------------------------ the invoice provider


@db
def test_an_order_is_billed_at_once_with_a_proforma(registry, monkeypatch):  # noqa: F811
    factory = registry[0]
    with factory() as s:
        account = _account(s)
        order, request = service.create(s, account.id, _profile_id(s, account), BUYER, today=YEAR)
        assert order.state == OrderState.INVOICED and order.provider == "invoice"
        assert request.kind == "proforma" and request.due == YEAR + dt.timedelta(days=8)
        proforma = s.scalar(select(Invoice).where(Invoice.order_id == order.id))
        assert proforma.kind == InvoiceKind.PROFORMA and proforma.number == request.reference
        assert request.reference.endswith("-2099-0001")
        assert float(proforma.total_mkd) == float(order.amount_mkd) + float(order.vat_mkd)


@db
def test_the_price_is_d1s_with_the_founding_price_while_it_lasts(registry, monkeypatch):  # noqa: F811
    from app.pricing import prices

    real = prices()
    one_founding = real.model_copy(
        update={
            "report": real.report.model_copy(
                update={"founding": real.report.founding.model_copy(update={"orders": 1})}
            )
        }
    )
    monkeypatch.setattr(service, "prices", lambda: one_founding)
    factory = registry[0]
    with factory() as s:
        account = _account(s)
        profile = _profile_id(s, account)
        if service.report_price(s) != 4900:
            pytest.skip("the development database already has a founding order")
        first, _ = service.create(s, account.id, profile, BUYER, today=YEAR)
        second, _ = service.create(s, account.id, profile, BUYER, today=YEAR)
        assert (float(first.amount_mkd), float(first.vat_mkd)) == (4900, 882)
        assert (float(second.amount_mkd), float(second.vat_mkd)) == (8900, 1602)
        # A cancelled order gives its founding place back.
        service.cancel(s, first)
        assert service.report_price(s) == 4900


@db
def test_numbers_are_gapless_per_kind_and_year(registry):  # noqa: F811
    factory = registry[0]
    with factory() as s:
        account = _account(s)
        profile = _profile_id(s, account)
        numbers = [
            service.create(s, account.id, profile, BUYER, today=YEAR)[1].reference for _ in range(3)
        ]
        assert [n.rsplit("-", 1)[-1] for n in numbers] == ["0001", "0002", "0003"]
        # A new fiscal year starts again at one.
        next_year = service.create(s, account.id, profile, BUYER, today=dt.date(2100, 1, 2))
        assert next_year[1].reference.endswith("-2100-0001")
        assert numbering.next_number(s, InvoiceKind.FINAL, 2099).endswith("-2099-0001")


@db
def test_a_reconciled_payment_marks_the_proforma_and_the_order(registry):  # noqa: F811
    factory = registry[0]
    with factory() as s:
        account = _account(s)
        order, _ = service.create(s, account.id, _profile_id(s, account), BUYER, today=YEAR)
        paid_at = dt.datetime(2099, 3, 4, 9, tzinfo=dt.UTC)
        service.confirm_payment(s, order, Evidence("НЛБ 20990304-117", at=paid_at))
        proforma = s.scalar(select(Invoice).where(Invoice.order_id == order.id))
        assert order.state == OrderState.PAID
        assert proforma.bank_reference == "НЛБ 20990304-117" and proforma.paid_at == paid_at
        with pytest.raises(states.IllegalTransition):
            service.cancel(s, order)  # paid: only a refund now


# ------------------------------------------------------------------ the acceptance


class FakeCard:
    """A card gateway as it would be added: a class with the two methods, registered."""

    name = "card"

    def __init__(self):
        self.asked, self.confirmed = [], []

    def request(self, session, order, today):
        self.asked.append(order.id)
        return PaymentRequest("redirect", f"https://pay.example.test/{order.id}", None, 0.0)

    def confirm(self, session, order, evidence):
        self.confirmed.append(evidence.reference)


@db
def test_a_card_gateway_plugs_in_without_touching_the_order_logic(registry, monkeypatch):  # noqa: F811
    card = FakeCard()
    monkeypatch.setitem(providers.PROVIDERS, "card", card)
    factory = registry[0]
    with factory() as s:
        account = _account(s)
        order, request = service.create(
            s, account.id, _profile_id(s, account), BUYER, provider="card", today=YEAR
        )
        assert request.kind == "redirect" and card.asked == [order.id]
        assert s.scalar(select(Invoice).where(Invoice.order_id == order.id)) is None
        service.confirm_payment(s, order, Evidence("txn-42"))
        assert order.state == OrderState.PAID and card.confirmed == ["txn-42"]


def test_the_order_logic_never_names_a_provider_or_reaches_a_model():
    """The service asks `provider_for`; the buyer's identity never meets the gateway."""
    package = Path(service.__file__).parent
    code = (package / "service.py").read_text(encoding="utf-8")
    assert "InvoiceProvider" not in code and "Invoice(" not in code
    for path in package.glob("*.py"):
        imports = re.findall(r"^(?:from|import) (\S+)", path.read_text(encoding="utf-8"), re.M)
        assert not [m for m in imports if m.startswith("app.ai")], path.name
