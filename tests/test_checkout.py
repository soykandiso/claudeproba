"""Checkout (roadmap P4 s50): order a detailed report, get a proforma within a minute.

Against PostgreSQL in a rolled-back transaction (stage 1's registry fixture), with mail
written to a temporary outbox, as the account tests do.
"""

import email

import pytest

from app import create_app
from app.config import load_settings
from app.web import account, checkout
from tests.test_account import ANSWERS, _ask, _csrf, _fresh, _link, _use
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

BUYER = {"name": "Проба ДООЕЛ", "address": "ул. Македонија 1, Скопје", "edb": "", "embs": ""}


@pytest.fixture
def site(registry, monkeypatch, tmp_path):  # noqa: F811
    factory = registry[0]
    monkeypatch.setattr(account, "_sessions", lambda: factory)
    monkeypatch.setattr(checkout, "_sessions", lambda: factory)
    app = create_app(load_settings(env="testing", outbox_dir=str(tmp_path / "outbox")))
    return app.test_client(), tmp_path / "outbox"


def _signed_in(client, outbox, profile=True):
    _ask(client, _fresh())
    _use(client, _link(outbox))
    if profile:
        client.post("/profil/", data={**ANSWERS, "csrf": _csrf(client)})


def _order(client, **buyer):
    return client.post("/naracka/", data={**BUYER, **buyer, "csrf": _csrf(client)})


@db
def test_ordering_asks_to_sign_in_and_comes_back(site):
    client, outbox = site
    away = client.get("/naracka/")
    assert away.status_code == 302 and "next=/naracka/" in away.location

    client.get(away.location)
    _ask(client, _fresh())
    back = _use(client, _link(outbox))
    assert back.status_code == 302 and back.location.endswith("/naracka/")


@pytest.mark.parametrize(
    "target", ["//evil.example", "/\\evil.example", "https://evil.example", "naracka"]
)
def test_only_this_sites_paths_are_returned_to(target):
    assert account.safe_next(target) is None


def test_a_path_on_this_site_is_returned_to():
    assert account.safe_next("/naracka/") == "/naracka/"


@db
def test_an_order_gets_a_proforma_by_mail_with_the_pdf(site):
    client, outbox = site
    _signed_in(client, outbox)
    page = client.get("/naracka/").get_data(as_text=True)
    assert "првите пет отворени повици" in page and "МКД" in page

    placed = _order(client, edb="MK 4030000000000", embs="1234567")
    assert placed.status_code == 302 and "sent=1" in placed.location

    newest = max(outbox.glob("*.eml"), key=lambda p: p.stat().st_mtime)
    message = email.message_from_bytes(newest.read_bytes())
    attached = [part for part in message.walk() if part.get_content_type() == "application/pdf"]
    assert len(attached) == 1 and attached[0].get_payload(decode=True).startswith(b"%PDF")

    shown = client.get(placed.location).get_data(as_text=True)
    assert "Чека уплата" in shown and "Цел на дознаката" in shown

    pdf = client.get(placed.location.split("?")[0] + "/profaktura.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert "filename*=UTF-8''" in pdf.headers["Content-Disposition"]

    assert "Детален извештај" in client.get("/smetka").get_data(as_text=True)


@db
@pytest.mark.parametrize(
    "buyer, field",
    [({"name": ""}, "називот"), ({"edb": "123"}, "13 цифри"), ({"embs": "12"}, "7 цифри")],
)
def test_wrong_details_are_said_and_nothing_is_ordered(site, buyer, field):
    client, outbox = site
    _signed_in(client, outbox)
    refused = _order(client, **buyer)
    assert refused.status_code == 422
    assert "Нарачката не е испратена" in refused.get_data(as_text=True)
    assert "Нарачки" not in client.get("/smetka").get_data(as_text=True)


@db
def test_no_order_without_a_profile(site):
    client, outbox = site
    _signed_in(client, outbox, profile=False)
    assert "Прво профил на фирмата" in client.get("/naracka/").get_data(as_text=True)
    assert _order(client).location.endswith("/profil/")


@db
def test_someone_elses_order_does_not_exist(site):
    client, outbox = site
    _signed_in(client, outbox)
    mine = _order(client).location.split("?")[0]

    client.post("/odjava", data={"csrf": _csrf(client)})
    _signed_in(client, outbox)
    assert client.get(mine).status_code == 404
    assert client.get(mine + "/profaktura.pdf").status_code == 404
