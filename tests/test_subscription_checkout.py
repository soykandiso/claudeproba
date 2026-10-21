"""The monitoring subscription on sale (21.10.2026): its order form, one at a time, its pages.

From /ceni to the order form, the proforma, the payment, the activation, the order page and
the account. Against PostgreSQL in a rolled-back transaction, as the checkout tests are.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models.commerce import Invoice, Order, Product
from app.models.enums import InvoiceKind, OrderState
from app.orders import fulfil, numbering, reconcile, service
from tests.test_account import _csrf
from tests.test_checkout import BUYER, _signed_in, site  # noqa: F401 (fixture)
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)


def _order(client, plan):
    return client.post("/naracka/sledenje", data={**BUYER, "plan": plan, "csrf": _csrf(client)})


@db
def test_signed_out_it_asks_to_sign_in_first(site):  # noqa: F811
    client, _ = site
    away = client.get("/naracka/sledenje")
    assert away.status_code == 302 and "next=/naracka/sledenje" in away.location


@db
def test_the_form_offers_two_plans_and_says_how_it_ends(site):  # noqa: F811
    client, outbox = site
    _signed_in(client, outbox)
    page = client.get("/naracka/sledenje").get_data(as_text=True)
    assert "Месечно, 1.200 МКД (1.416 МКД)" in page and "Годишно, 12.000 МКД (14.160 МКД)" in page
    assert "Ништо не се наплатува автоматски" in page and "со еден клик" in page
    assert "не се враќа" in page  # said before paying


@db
def test_a_yearly_order_gets_its_proforma_and_its_page(site, registry):  # noqa: F811
    client, outbox = site
    _signed_in(client, outbox)
    placed = _order(client, service.YEAR)
    assert placed.status_code == 302 and "sent=1" in placed.location
    order_id = uuid.UUID(placed.location.split("/naracka/")[1].split("?")[0])
    with registry[0]() as s:
        order = s.get(Order, order_id)
        assert float(order.amount_mkd) == 12000
        assert s.scalar(select(Product.sku).where(Product.id == order.product_id)) == service.YEAR
    assert "Следење на нови повици, годишно" in client.get(placed.location).get_data(as_text=True)


@db
def test_a_wrong_plan_is_said(site):  # noqa: F811
    client, outbox = site
    _signed_in(client, outbox)
    refused = _order(client, "monitoring-week")
    assert refused.status_code == 422 and "Изберете месечно или годишно" in refused.get_data(
        as_text=True
    )


@db
def test_paid_it_is_active_and_a_second_is_not_sold(site, registry, tmp_path):  # noqa: F811
    client, outbox = site
    _signed_in(client, outbox)
    order_id = uuid.UUID(_order(client, service.MONTH).location.split("/naracka/")[1].split("?")[0])
    # The site and the worker share one store, as on the server.
    app = client.application
    settings = app.extensions["settings"].model_copy(
        update={"snapshot_dir": str(tmp_path / "store")}
    )
    app.extensions["settings"] = settings
    with registry[0]() as s:
        pro = s.scalar(
            select(Invoice).where(
                Invoice.order_id == order_id, Invoice.kind == InvoiceKind.PROFORMA
            )
        )
        reconcile.confirm(s, pro.id, Decimal(pro.total_mkd), "ref", numbering.today())
        s.commit()
        fulfil.subscription_job(s, settings, order_id)
        assert s.get(Order, order_id).state == OrderState.DELIVERED

    page = client.get(f"/naracka/{order_id}").get_data(as_text=True)
    assert "Активно до" in page and "Управување со следењето" in page
    assert client.get(f"/naracka/{order_id}/faktura.pdf").status_code == 200
    assert client.get(f"/naracka/{order_id}/izveshtaj.pdf").status_code == 404

    again = client.get("/naracka/sledenje").get_data(as_text=True)
    assert "Веќе го следите" in again and 'name="plan"' not in again
    assert _order(client, service.YEAR).location.endswith("/smetka#following-h")


@db
def test_the_account_offers_it_when_there_is_none(site):  # noqa: F811
    client, outbox = site
    _signed_in(client, outbox)
    home = client.get("/smetka").get_data(as_text=True)
    assert 'href="/naracka/sledenje"' in home
