import re

import pytest

from app import create_app
from app.config import load_settings
from app.models.enums import Verdict
from app.web.demo import data, engine

PAGES = [
    "/demo/",
    "/demo/vodic",
    "/demo/profil",
    "/demo/lista",
    "/demo/izvestaj/fitr-novoosnovani",
    "/demo/izvor/snap_7f3a1c?od=100&do=140",
    "/demo/smetka",
    "/demo/sledenje",
    "/demo/admin",
    "/demo/admin/povik/met-izvoz",
]
BANNED = ["гарантирано", "guaranteed", "approved", "you will receive", "одобрено"]
BUYER = {
    "name": "Пример Софтвер ДООЕЛ",
    "embs": "1234567",
    "edb": "MK4030012345678",
    "city": "Скопје",
    "email": "kontakt@primer.mk",
}


@pytest.mark.parametrize("path", PAGES)
def test_demo_pages_render_in_macedonian_with_demo_notice(client, path):
    client.post("/demo/primer-profil")
    body = client.get(path).get_data(as_text=True)

    assert 'lang="mk"' in body
    assert "Демо верзија" in body
    for word in BANNED:
        assert word not in body.lower()


def test_unknown_report_is_404(client):
    assert client.get("/demo/izvestaj/ne-postoi").status_code == 404


def test_unpublished_call_is_not_reachable_by_customers(client):
    assert client.get("/demo/izvestaj/met-izvoz").status_code == 404


def test_demo_is_not_registered_in_production():
    """Invented calls and citations must never be publicly reachable."""
    app = create_app(load_settings(env="production", version="test", secret_key="x" * 40))

    assert "demo" not in app.blueprints


def test_dates_are_dd_mm_yyyy(client):
    client.post("/demo/primer-profil")
    body = client.get("/demo/lista").get_data(as_text=True)

    assert re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", body)
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", body)


def test_every_published_citation_round_trips_to_its_quote():
    """No citation, no claim: offsets shown to a user point at exactly the quote."""
    for call in data.all_calls():
        if not call.published:
            continue
        for criterion in call.criteria:
            c = call.citation(criterion)
            assert c is not None, (call.slug, criterion.key)
            assert call.document_text[c.char_start : c.char_end] == criterion.quote


def test_pending_call_has_a_paraphrased_quote_for_the_reviewer_to_catch():
    call = data.find("met-izvoz")
    age = next(c for c in call.criteria if c.key == "age")

    assert call.citation(age) is None
    assert call.citation(age, age.corrected_quote) is not None


def test_intake_errors_are_shown_and_nothing_is_saved(client):
    form = dict(engine.DEFAULT_ANSWERS, founded="20x", nace="програмирање")
    del form["inv"]
    response = client.post("/demo/profil", data=form)
    body = response.get_data(as_text=True)

    assert response.status_code == 422
    assert "Внесете година со четири цифри" in body
    assert "Почнете со шифрата" in body
    assert "Листата се прави од профилот" in client.get("/demo/lista").get_data(as_text=True)


def test_profile_changes_the_shortlist(client):
    it = dict(engine.DEFAULT_ANSWERS)
    client.post("/demo/profil", data=it)
    body = client.get("/demo/lista").get_data(as_text=True)
    assert "повици, подредени" in body

    hotel = dict(it, nace="55.10 Хотели", inv=["equipment"])
    client.post("/demo/profil", data=hotel)
    profile = engine.normalise(engine.clean_answers(_form(hotel))[0])
    tourism = engine.match(data.find("apptr-smestuvanje"), profile)
    assert tourism.verdict == Verdict.ELIGIBLE


def _form(d):
    from werkzeug.datastructures import MultiDict

    items = []
    for k, v in d.items():
        items += [(k, x) for x in v] if isinstance(v, list) else [(k, v)]
    return MultiDict(items)


def test_farm_passes_ipard_rule_and_company_does_not():
    ipard = data.find("ipard-merka-1")
    company = engine.normalise(engine.DEFAULT_ANSWERS)
    farm = engine.normalise(dict(engine.DEFAULT_ANSWERS, entity="farm", nace="01.13"))

    assert engine.match(ipard, company).verdict == Verdict.NOT_ELIGIBLE
    assert engine.match(ipard, farm).verdict == Verdict.LIKELY_ELIGIBLE


def test_model_answers_never_exclude():
    """A recorded not_satisfied from the text check is needs_verification (invariant 1)."""
    green = data.find("skopje-zeleni")
    profile = engine.normalise(engine.DEFAULT_ANSWERS)  # digital, not green
    m = engine.match(green, profile)

    model = [r for r in m.results if r.decision.decided_by == "model"]
    assert model and all(r.verdict == Verdict.NEEDS_VERIFICATION for r in model)
    assert m.verdict == Verdict.NEEDS_VERIFICATION


def test_founding_year_straddling_a_threshold_is_unclear_not_excluded():
    fitr = data.find("fitr-novoosnovani")
    from datetime import date

    six_years_ago = str(date.today().year - 6)
    profile = engine.normalise(dict(engine.DEFAULT_ANSWERS, founded=six_years_ago))
    age = next(r for r in engine.match(fitr, profile).results if r.criterion.key == "age")

    assert age.verdict == Verdict.NEEDS_VERIFICATION


def test_scrubber_removes_contact_details_from_the_description(client):
    answers = dict(
        engine.DEFAULT_ANSWERS, description="Софтвер, јавете се на 070 123 456 или ana@firma.mk"
    )
    client.post("/demo/profil", data=answers)
    body = client.get("/demo/lista").get_data(as_text=True)

    assert "070 123 456" not in body.split('id="model-h"')[1]
    assert "ana@firma.mk" not in body.split('id="model-h"')[1]


def test_order_payment_review_delivery(client):
    client.post("/demo/primer-profil")

    bad = client.post("/demo/naracka/fitr-novoosnovani/report", data=dict(BUYER, embs="12"))
    assert bad.status_code == 422

    r = client.post("/demo/naracka/fitr-novoosnovani/report", data=BUYER)
    assert r.headers["Location"].endswith("/demo/naracki/1")
    invoice = client.get("/demo/naracki/1").get_data(as_text=True)
    assert "0001/" in invoice
    assert "10.502" in invoice  # 8.900 + 18% ДДВ

    assert client.get("/demo/naracki/1/izvestaj").status_code == 404  # not before review
    client.post("/demo/naracki/1/uplata", data={"bank_ref": "ИЗВ-001"})
    review = client.get("/demo/admin/naracka/1").get_data(as_text=True)
    assert "Забранети изрази:</strong> нема" in review
    client.post("/demo/admin/naracka/1", data={"action": "accept"})

    report = client.get("/demo/naracki/1/izvestaj")
    assert report.status_code == 200
    assert "Прегледано од консултант" in report.get_data(as_text=True)


def test_package_marks_financial_fields_for_the_applicant(client):
    client.post("/demo/primer-profil")
    client.post("/demo/naracka/fitr-novoosnovani/package", data=BUYER)
    client.post("/demo/naracki/1/uplata")
    client.post("/demo/admin/naracka/1", data={"action": "accept"})
    body = client.get("/demo/naracki/1/paket").get_data(as_text=True)

    assert "Нацрт за дополнување" in body
    assert body.count('class="unfilled"') >= 4


def test_call_with_unverified_quote_cannot_be_published_until_fixed(client):
    client.post("/demo/primer-profil")
    client.post("/demo/sledenje", data={"frequency": "weekly"})

    assert client.post("/demo/admin/povik/met-izvoz", data={"action": "accept"}).status_code == 409
    assert "Поддршка за извозно" not in client.get("/demo/lista").get_data(as_text=True)

    client.post("/demo/admin/povik/met-izvoz/citat/age")
    client.post("/demo/admin/povik/met-izvoz", data={"action": "accept"})

    assert "Поддршка за извозно" in client.get("/demo/lista").get_data(as_text=True)
    assert "Нов јавен повик за вашата фирма" in client.get("/demo/sledenje").get_data(as_text=True)


def test_reset_clears_the_sandbox(client):
    client.post("/demo/primer-profil")
    client.post("/demo/reset")

    assert "Листата се прави од профилот" in client.get("/demo/lista").get_data(as_text=True)


def test_demo_weights_sum_to_one():
    version, weights = engine.weights()

    assert version == "demo-1"
    assert abs(sum(weights.values()) - 1) < 1e-9
