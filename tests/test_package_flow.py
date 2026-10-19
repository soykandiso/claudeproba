"""A document package from the order form to the buyer's download (roadmap P5 s75).

The acceptance: "a complete draft package produced and human-reviewed". A buyer orders a package
for an open call, pays, the package is made and waits in the review queue; a person opens it and
approves; it reaches the buyer with the invoice, and the order page serves it as sent.
"""

import datetime as dt
import email
import io
import uuid
import zipfile
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import create_app
from app.config import load_settings
from app.documents import label
from app.ingestion.snapshots import SnapshotStore
from app.models import Call, Programme, ReviewQueueItem, SourceFeed
from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind, OrderState, ReviewKind
from app.orders import fulfil, numbering, reconcile
from app.orders.deliver import DOCX
from app.pricing import prices
from app.web import checkout
from tests.test_account import _csrf
from tests.test_checkout import BUYER, _signed_in
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

MSP = "ЈАВЕН ПОВИК за финансиска поддршка на микро, мали и средни претпријатија и занаетчии"
# The business date (Skopje's), as the code under test uses it: this machine's clock may
# be on another day near midnight.
TODAY = numbering.today()


def _open(monkeypatch, package=True):
    on = prices().model_copy(
        update={"package": prices().package.model_copy(update={"orderable": package})}
    )
    for target in (
        "app.pricing.prices",
        "app.web.checkout.prices",
        "app.web.public.prices",
        "app.orders.service.prices",
    ):
        monkeypatch.setattr(target, lambda on=on: on)


@pytest.fixture
def site(registry, monkeypatch, tmp_path):  # noqa: F811
    factory = registry[0]
    store = SnapshotStore(tmp_path / "store")
    for module in ("app.web.account", "app.web.checkout", "app.web.admin"):
        monkeypatch.setattr(f"{module}._sessions", lambda: factory)
    monkeypatch.setattr("app.web.admin._store", lambda: store)
    monkeypatch.setattr(checkout, "open_calls", lambda db, profile: 5)
    settings = load_settings(
        env="testing", outbox_dir=str(tmp_path / "outbox"), snapshot_dir=str(store.root)
    )
    app = create_app(settings)
    return app.test_client(), factory, tmp_path / "outbox", store, settings


def _call(factory, *, title=MSP, deadline=None) -> uuid.UUID:
    with factory() as s:
        source = s.scalar(select(SourceFeed).where(SourceFeed.slug == "economy"))
        programme = Programme(
            source_feed_id=source.id,
            slug=f"t-{uuid.uuid4().hex[:8]}",
            name_mk=title,
            institution="Министерство за економија и труд",
        )
        s.add(programme)
        s.flush()
        call = Call(
            programme_id=programme.id,
            source_feed_id=source.id,
            title_mk=title,
            canonical_url="https://www.economy.gov.mk/x",
            is_published=True,
            deadline_at=deadline or dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
        )
        s.add(call)
        s.commit()
        return call.id


@db
def test_packages_are_not_sold_while_the_switch_is_off(site, monkeypatch):
    client, factory, outbox, *_ = site
    _open(monkeypatch, package=False)
    _signed_in(client, outbox)
    assert client.get(f"/naracka/paket/{_call(factory)}").status_code == 404


@db
def test_a_package_is_offered_only_for_an_open_call_that_has_one(site, monkeypatch):
    client, factory, outbox, *_ = site
    _open(monkeypatch)
    _signed_in(client, outbox)
    page = client.get(f"/naracka/paket/{_call(factory)}").get_data(as_text=True)
    assert "Пакет на документи" in page and "2.900 МКД" in page and "Што не е во пакетот" in page
    assert "Барање за финансиска поддршка" in page
    closed = _call(factory, deadline=dt.datetime.now(dt.UTC) - dt.timedelta(days=1))
    assert client.get(f"/naracka/paket/{closed}").status_code == 404
    assert (
        client.get(
            f"/naracka/paket/{_call(factory, title='Национална награда за БЗР')}"
        ).status_code
        == 404
    )


@db
def test_from_the_order_form_to_the_buyers_download(site, monkeypatch):
    client, factory, outbox, store, settings = site
    _open(monkeypatch)
    _signed_in(client, outbox)
    call_id = _call(factory)

    # The buyer orders and gets the proforma.
    placed = client.post(f"/naracka/paket/{call_id}", data={**BUYER, "csrf": _csrf(client)})
    assert placed.status_code == 302 and "sent=1" in placed.location
    order_id = uuid.UUID(placed.location.split("/naracka/")[1].split("?")[0])
    page = client.get(placed.location).get_data(as_text=True)
    assert "Пакет на документи за повикот" in page

    # The transfer arrives; the worker makes the package and queues it.
    with factory() as s:
        proforma = s.scalar(
            select(Invoice).where(
                Invoice.order_id == order_id, Invoice.kind == InvoiceKind.PROFORMA
            )
        )
        assert Decimal(proforma.total_mkd) == Decimal("3422.00")
        reconcile.confirm(s, proforma.id, Decimal(proforma.total_mkd), "ref", TODAY)
        item_id = fulfil.package_job(s, settings, order_id)["review_item_id"]
        s.commit()

    # A person opens it: every document and the checklist, each form's source.
    admin = client.get("/admin/").get_data(as_text=True)
    assert "Пакети што чекаат, 1" in admin
    review = client.get(f"/admin/paket/{item_id}").get_data(as_text=True)
    assert "portal.mdt.gov.mk" in review and "Прифаќањето го испраќа пакетот" in review
    first = client.get(f"/admin/paket/{item_id}/dokument/1")
    assert first.status_code == 200 and label.is_labelled(first.data)
    assert client.get(f"/admin/paket/{item_id}/dokument/0").status_code == 200

    # Approved: it goes to the buyer with the invoice.
    done = client.post(
        f"/admin/paket/{item_id}/odobri", data={"csrf": _csrf(client)}, follow_redirects=True
    )
    assert "Пакетот е испратен на" in done.get_data(as_text=True)
    with factory() as s:
        order = s.get(Order, order_id)
        assert order.state == OrderState.DELIVERED
        archive = store.get(order.report_storage_key)
    names = zipfile.ZipFile(io.BytesIO(archive)).namelist()
    assert len(names) == 4 and names[-1] == "Што уште треба да подготвите.docx"

    sent = email.message_from_bytes(
        max(outbox.glob("*.eml"), key=lambda p: p.stat().st_mtime).read_bytes()
    )
    attached = [p.get_content_type() for p in sent.walk() if p.get_filename()]
    assert attached.count(DOCX) == 4  # three forms and the checklist
    assert attached.count("application/pdf") == 1  # the invoice

    # The buyer's page serves the package as sent; it is not a report.
    mine = client.get(f"/naracka/{order_id}").get_data(as_text=True)
    assert "Пакет (ZIP)" in mine
    assert client.get(f"/naracka/{order_id}/paket.zip").data == archive
    assert client.get(f"/naracka/{order_id}/izveshtaj.pdf").status_code == 404


@db
def test_a_package_with_a_missing_file_is_not_approved_and_closing_needs_a_reason(
    site, monkeypatch
):
    client, factory, outbox, store, settings = site
    _open(monkeypatch)
    _signed_in(client, outbox)
    placed = client.post(f"/naracka/paket/{_call(factory)}", data={**BUYER, "csrf": _csrf(client)})
    order_id = uuid.UUID(placed.location.split("/naracka/")[1].split("?")[0])
    with factory() as s:
        proforma = s.scalar(
            select(Invoice).where(
                Invoice.order_id == order_id, Invoice.kind == InvoiceKind.PROFORMA
            )
        )
        reconcile.confirm(s, proforma.id, Decimal(proforma.total_mkd), "ref", TODAY)
        item_id = fulfil.package_job(s, settings, order_id)["review_item_id"]
        item = s.get(ReviewQueueItem, item_id)
        assert item.kind == ReviewKind.DOCUMENT_PACKAGE
        key = item.payload["documents"][0]["key"]
        s.commit()
    (store.root / key).unlink()  # a file lost from the store

    refused = client.post(f"/admin/paket/{item_id}/odobri", data={"csrf": _csrf(client)})
    assert refused.status_code == 422 and "датотеката ја нема" in refused.get_data(as_text=True)
    unexplained = client.post(
        f"/admin/paket/{item_id}/zatvori", data={"csrf": _csrf(client), "note": " "}
    )
    assert unexplained.status_code == 422
    closed = client.post(
        f"/admin/paket/{item_id}/zatvori",
        data={"csrf": _csrf(client), "note": "образецот е стар"},
        follow_redirects=True,
    )
    assert "нема да се испрати" in closed.get_data(as_text=True)
    with factory() as s:
        assert s.get(Order, order_id).state == OrderState.IN_PROGRESS


@db
def test_the_shortlist_offers_a_package_for_a_call_that_has_one(site, monkeypatch):
    from types import SimpleNamespace

    from app.web import shortlist

    _, factory, *_ = site
    with_package, without = _call(factory), _call(factory, title="Национална награда за БЗР")
    with factory() as s:
        entries = [SimpleNamespace(call=s.get(Call, i)) for i in (with_package, without)]
        _open(monkeypatch)
        offered = shortlist._packages(s, entries)
        assert list(offered) == [with_package] and offered[with_package].slug == "economy-msp"
        _open(monkeypatch, package=False)
        assert shortlist._packages(s, entries) == {}
