"""Document packages: the catalogue, the facts, and a paid order's package (roadmap P5 s75).

The package is made from the order's buyer, the profile and the call, filled, labelled, stored
as made and queued for a person's review. Against PostgreSQL in a rolled-back transaction.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.documents import label, packages
from app.ingestion.snapshots import SnapshotStore
from app.models import Call, Programme, ReviewQueueItem, SourceFeed
from app.models.commerce import Order
from app.models.documents import DocumentPackage, DocumentTemplate, GeneratedDocument
from app.models.enums import OrderState, ReviewKind
from app.orders import fulfil, numbering, reconcile, service
from tests.test_account import ANSWERS
from tests.test_accounts import _account
from tests.test_orders import BUYER, _profile_id
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

# The business date (Skopje's), as the code under test uses it: this machine's clock may
# be on another day near midnight.
TODAY = numbering.today()
MSP = "ЈАВЕН ПОВИК за финансиска поддршка на микро, мали и средни претпријатија и занаетчии"


# ------------------------------------------------------------------ the catalogue


def test_every_package_names_templates_that_exist_and_can_be_filled():
    assert packages.check() == []
    assert set(packages.catalogue()) == {
        "av-rabotodavaci",
        "economy-msp",
        "economy-socijalni-praktiki",
        "economy-univerziteti",
    }


@pytest.mark.parametrize(
    "source, title, slug",
    [
        ("economy", MSP, "economy-msp"),
        (
            "economy",
            "Јавен повик ... социјално прифатливи практики на деловните субјекти",
            "economy-socijalni-praktiki",
        ),
        (
            "economy",
            "Соработка ... и универзитетите преку заеднички проекти",
            "economy-univerziteti",
        ),
        ("av", "Јавен повик до работодавачите за мерката 4. Практикантство", "av-rabotodavaci"),
        ("economy", "Национална награда за БЗР", None),  # an economy call no package fits
        ("ipard", "Јавен повик 02/2025", None),
    ],
)
def test_a_call_gets_the_one_package_that_fits_or_none(source, title, slug):
    found = packages.for_call(source, title)
    assert (found.slug if found else None) == slug


def test_two_packages_fitting_one_call_is_none_not_a_guess(monkeypatch):
    twice = {
        **packages.catalogue(),
        "copy": packages.catalogue()["economy-msp"].model_copy(update={"slug": "copy"}),
    }
    monkeypatch.setattr(packages, "catalogue", lambda: twice)
    assert packages.for_call("economy", MSP) is None


# ------------------------------------------------------------------ the facts and the package


def test_the_facts_come_from_the_order_the_profile_and_the_call():
    order = Order(
        buyer_name="Пекара Проба ДООЕЛ",
        buyer_address="ул. 1, Скопје",
        buyer_edb="4030000000000",
        buyer_embs="1234567",
    )
    call = Call(title_mk=MSP, deadline_at=dt.datetime(2026, 11, 30, 22, 59, tzinfo=dt.UTC))
    facts = packages.facts_from(order, ANSWERS, call, "Министерство за економија и труд", TODAY)
    values = facts.values(TODAY)
    assert (
        values["applicant_name"] == "Пекара Проба ДООЕЛ" and values["applicant_embs"] == "1234567"
    )
    assert values["applicant_municipality"] == "Центар" and values["applicant_founded"] == 2010
    assert values["applicant_activity"].startswith("10.71")
    assert values["call_deadline"] == dt.date(2026, 11, 30)  # Skopje's date, not UTC's


def test_a_package_is_every_document_filled_and_labelled_with_its_checklist():
    facts = packages.Facts(buyer_name="Пекара", buyer_embs="7654321", founded=2010, call_title=MSP)
    made = packages.assemble(packages.catalogue()["economy-msp"], facts, TODAY)
    assert len(made.documents) == 3 and all(label.is_labelled(d.docx) for d in made.documents)
    keys = {i.key for i in made.checklist}
    assert {"requested_amount", "tekovna_sostojba", "notarska_zaverka"} <= keys
    assert made.checklist_docx.startswith(b"PK")


# ------------------------------------------------------------------ a paid package order


def _economy_call(s) -> Call:
    source = s.scalar(select(SourceFeed).where(SourceFeed.slug == "economy"))
    programme = Programme(
        source_feed_id=source.id,
        slug=f"test-msp-{uuid.uuid4().hex[:8]}",
        name_mk=MSP,
        institution="Министерство за економија и труд",
    )
    s.add(programme)
    s.flush()
    call = Call(
        programme_id=programme.id,
        source_feed_id=source.id,
        title_mk=MSP,
        canonical_url="https://www.economy.gov.mk/x",
    )
    s.add(call)
    s.flush()
    return call


@db
def test_a_paid_package_order_is_made_stored_and_queued_for_review(registry, tmp_path):  # noqa: F811
    store = SnapshotStore(tmp_path)
    with registry[0]() as s:
        account = _account(s)
        call = _economy_call(s)
        order, request = service.create_package(
            s, account.id, _profile_id(s, account), call.id, BUYER, today=TODAY
        )
        assert float(order.amount_mkd) == 2900 and service.sku_of(s, order) == service.PACKAGE
        proforma = reconcile.match(s, request.reference)[0][0].open.invoice
        reconcile.confirm(s, proforma.id, Decimal(proforma.total_mkd), "ref", TODAY)

        settings = type("S", (), {"snapshot_dir": str(tmp_path)})()
        done = fulfil.package_job(s, settings, order.id)
        assert s.get(Order, order.id).state == OrderState.IN_PROGRESS

        item = s.get(ReviewQueueItem, done["review_item_id"])
        assert item.kind == ReviewKind.DOCUMENT_PACKAGE and item.order_id == order.id
        assert item.payload["package"] == "economy-msp" and len(item.payload["documents"]) == 3

        package = s.scalar(select(DocumentPackage).where(DocumentPackage.order_id == order.id))
        made = s.scalars(
            select(GeneratedDocument).where(GeneratedDocument.package_id == package.id)
        ).all()
        assert len(made) == 4 and not any(g.is_ai_assisted for g in made)  # 3 forms + the checklist
        assert all(label.is_labelled(store.get(g.storage_key)) for g in made if g.template_id)
        templates = s.scalars(
            select(DocumentTemplate).where(
                DocumentTemplate.id.in_([g.template_id for g in made if g.template_id])
            )
        ).all()
        assert all(len(t.sha256) == 64 for t in templates) and package.checklist

        # A second run of the job (the sweep, a retry) makes nothing twice.
        assert fulfil.package_job(s, settings, order.id)["skipped"]


@db
def test_a_call_no_package_fits_any_more_is_said_not_guessed(registry, tmp_path, monkeypatch):  # noqa: F811
    with registry[0]() as s:
        account = _account(s)
        call = _economy_call(s)
        order, _ = service.create_package(
            s, account.id, _profile_id(s, account), call.id, BUYER, today=TODAY
        )
        monkeypatch.setattr(packages, "catalogue", lambda: {})
        with pytest.raises(packages.PackageRefused, match="no package"):
            packages.prepare(s, SnapshotStore(tmp_path), order.id, TODAY)


@db
def test_report_and_package_orders_do_not_share_the_founding_places(registry):  # noqa: F811
    with registry[0]() as s:
        account = _account(s)
        call = _economy_call(s)
        before = service.report_price(s)
        for _ in range(3):
            service.create_package(
                s, account.id, _profile_id(s, account), call.id, BUYER, today=TODAY
            )
        assert service.report_price(s) == before
