"""The proforma PDF (roadmap P4 s49).

The row's acceptance, "an accountant reviews a sample and confirms it is compliant", is a
person's (`flask invoices sample`); these tests hold what the code can: every field there,
amounts that add up, the seller's gaps visible and blocking, and the PDF in our fonts only.
"""

import datetime as dt
import re

import pytest
from sqlalchemy import select

from app.models.commerce import Invoice
from app.models.enums import InvoiceKind
from app.orders import proforma, service
from tests.test_accounts import _account
from tests.test_orders import BUYER, YEAR, _profile_id
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

SELLER = proforma.Seller(
    name="Пример Издавач ДОО Скопје",
    address="ул. Издавачка бр. 2, 1000 Скопје",
    embs="7654321",
    edb="МК4030000000001",
    bank_account="300000000000001",
    bank="Пример банка АД Скопје",
    place="Скопје",
)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_the_proforma_carries_every_field(monkeypatch):
    monkeypatch.setattr(proforma, "seller", lambda: SELLER)
    invoice, order = proforma.sample()
    text = _text(proforma.html_of(invoice, order))
    for field in (
        f"бр. {invoice.number}",
        f"Издадена: {invoice.issued_at:%d.%m.%Y}",
        f"Рок за плаќање: {invoice.due_at:%d.%m.%Y}",
        "ЕМБС: 7654321",
        "ЕДБ: МК4030000000001",
        "Жиро сметка: 300000000000001, Пример банка АД Скопје",
        "Пример ДООЕЛ Скопје",
        "ЕДБ: МК4000000000000",
        "Основица 8.900,00 МКД",
        "ДДВ 18% 1.602,00 МКД",
        "Вкупно за плаќање 10.502,00 МКД",
        f"Цел на дознаката: профактура {invoice.number}",
        "Ова е профактура, не фискална фактура",
    ):
        assert field in text, field
    assert "[се утврдува]" not in text


def test_an_undecided_seller_shows_and_blocks(app):
    """Until D4 is confirmed: placeholders on the page, and the launch check fails."""
    invoice, order = proforma.sample()
    assert "[се утврдува]" in proforma.html_of(invoice, order)
    result = app.test_cli_runner().invoke(args=["invoices", "check"])
    assert result.exit_code == 1 and "seller.edb" in result.output


def test_the_amounts_add_up():
    invoice, _order = proforma.sample()
    assert float(invoice.amount_mkd) + float(invoice.vat_mkd) == float(invoice.total_mkd)
    assert proforma._denars(10502) == "10.502,00" and proforma._denars(1602.5) == "1.602,50"


def test_the_pdf_is_set_in_our_fonts_only(monkeypatch):
    monkeypatch.setattr(proforma, "seller", lambda: SELLER)
    invoice, order = proforma.sample()
    document = proforma.pdf(invoice, order)
    assert document.startswith(b"%PDF")
    from app.reports import render

    fonts = render.embedded_fonts(document)
    assert fonts and all(render._ours(f) for f in fonts)


def test_only_a_proforma_is_printed_as_one():
    invoice, order = proforma.sample()
    invoice.kind = InvoiceKind.FINAL
    with pytest.raises(proforma.ProformaRefused):
        proforma.pdf(invoice, order)


@db
def test_a_real_orders_proforma_renders(registry, monkeypatch):  # noqa: F811
    """From s48's service to a PDF: the row is what the PDF is made from, every time."""
    monkeypatch.setattr(proforma, "seller", lambda: SELLER)
    factory = registry[0]
    with factory() as s:
        account = _account(s)
        order, request = service.create(s, account.id, _profile_id(s, account), BUYER, today=YEAR)
        invoice = s.scalar(select(Invoice).where(Invoice.order_id == order.id))
        html = _text(proforma.html_of(invoice, order))
        assert f"бр. {request.reference}" in html and "Измислена ДОО" in html
        assert proforma.pdf(invoice, order).startswith(b"%PDF")
        assert invoice.issued_at == YEAR and invoice.due_at == YEAR + dt.timedelta(days=8)
