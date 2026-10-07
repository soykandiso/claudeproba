"""Signing in by e-mail link, and saved profiles (roadmap P3 s44).

The acceptance: "sign-in works with no password anywhere in the system". Against
PostgreSQL in a rolled-back transaction (stage 1's registry fixture), with mail written
to a temporary outbox.
"""

import email
import re
import uuid
from email.header import decode_header
from pathlib import Path

import pytest
from sqlalchemy import select

from app import create_app, mail
from app.config import load_settings
from app.models import Account, ApplicantProfile
from app.web import account
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "web" / "templates"
ANSWERS = {
    "entity": "doo",
    "municipality": "MK00814",  # Центар
    "founded": "2010",
    "employees": "10-49",
    "nace": "10.71",
    "amount": "3-10",
}


@pytest.fixture
def site(registry, monkeypatch, tmp_path):  # noqa: F811
    factory = registry[0]
    monkeypatch.setattr(account, "_sessions", lambda: factory)
    app = create_app(load_settings(env="testing", outbox_dir=str(tmp_path / "outbox")))
    return app.test_client(), factory, tmp_path / "outbox"


def _csrf(client) -> str:
    # The session's token, minted if no page has yet (a signed-in /najava redirects).
    with client.session_transaction() as s:
        return s.setdefault("csrf", "test-token")


def _fresh() -> str:
    # An address no earlier run left behind: the registry transaction sees the dev database.
    return f"proba-{uuid.uuid4().hex[:8]}@example.test"


def _ask(client, address):
    return client.post("/najava", data={"csrf": _csrf(client), "email": address})


def _link(outbox: Path) -> str:
    newest = max(outbox.glob("*.eml"), key=lambda p: p.stat().st_mtime)
    body = email.message_from_bytes(newest.read_bytes()).get_payload(decode=True).decode()
    return re.search(r"http://localhost/(najava/\S+)", body).group(1)


def _use(client, link):
    return client.post(f"/{link}", data={"csrf": _csrf(client)})


@db
def test_a_link_signs_in_once_and_only_by_its_button(site):
    client, factory, outbox = site
    me = _fresh()
    assert "Испративме линк за најава" in _ask(client, me).get_data(as_text=True)
    link = _link(outbox)

    # Opening the link, as a mail scanner does, signs no one in.
    assert "Најави се" in client.get(f"/{link}").get_data(as_text=True)
    assert client.get("/smetka").status_code == 302

    # The button does, and the account exists from that moment.
    assert _use(client, link).headers["Location"].endswith("/smetka")
    assert me in client.get("/smetka").get_data(as_text=True)
    with factory() as s:
        found = s.scalar(select(Account).where(Account.email == me))
        assert found.email_verified_at and found.last_seen_at

    # A used link is spent.
    second = _use(client.application.test_client(), link)
    assert second.status_code == 400 and "веќе искористен" in second.get_data(as_text=True)


@db
def test_asking_never_says_whether_an_account_exists(site):
    client, _factory, outbox = site
    me = _fresh()
    first = _ask(client, me).get_data(as_text=True)
    _use(client, _link(outbox))
    other = client.application.test_client()
    again = _ask(other, me).get_data(as_text=True)
    assert first.count("Испративме линк за најава") == again.count("Испративме линк за најава") == 1


@db
def test_an_address_asked_for_is_not_stored_until_its_link_is_used(site):
    client, factory, _outbox = site
    me = _fresh()
    _ask(client, me)
    with factory() as s:
        assert s.scalar(select(Account).where(Account.email == me)) is None


@db
def test_an_expired_or_forged_link_is_refused(site, monkeypatch):
    client, _factory, outbox = site
    _ask(client, _fresh())
    link = _link(outbox)
    forged = _use(client, link[:-3] + "abc")
    assert forged.status_code == 400 and "не е важечки" in forged.get_data(as_text=True)
    monkeypatch.setattr(account, "LINK_MINUTES", -1)
    expired = _use(client, link)
    assert expired.status_code == 400 and "истече" in expired.get_data(as_text=True)


@db
def test_asking_is_limited_per_browser(site):
    client, _factory, _outbox = site
    for _ in range(account.SENT_LIMIT):
        assert _ask(client, _fresh()).status_code == 200
    assert _ask(client, _fresh()).status_code == 429


def test_an_address_that_is_not_one_is_said_so(client):
    client.get("/najava")
    with client.session_transaction() as s:
        token = s["csrf"]
    response = client.post("/najava", data={"csrf": token, "email": "не-е-адреса"})
    assert response.status_code == 422 and "не изгледа како адреса" in response.get_data(
        as_text=True
    )


# ------------------------------------------------------------------ saved profiles


@db
def test_a_signed_in_profile_is_kept_as_versions(site):
    client, factory, outbox = site
    me = _fresh()
    _ask(client, me)
    _use(client, _link(outbox))

    for amount in ("3-10", "gt10"):
        client.post("/profil/", data={**ANSWERS, "amount": amount, "csrf": _csrf(client)})

    with factory() as s:
        rows = s.scalars(
            select(ApplicantProfile)
            .join(Account, Account.id == ApplicantProfile.account_id)
            .where(Account.email == me)
            .order_by(ApplicantProfile.version)
        ).all()
    assert [r.version for r in rows] == [1, 2]
    assert rows[0].superseded_at is not None and rows[1].superseded_at is None
    assert rows[1].answers["amount"] == "gt10"  # the old version is never edited
    assert "Зачуван на" in client.get("/smetka").get_data(as_text=True)


@db
def test_signing_in_on_another_device_brings_the_profile_back(site):
    client, _factory, outbox = site
    me = _fresh()
    _ask(client, me)
    _use(client, _link(outbox))
    client.post("/profil/", data={**ANSWERS, "csrf": _csrf(client)})
    client.post("/odjava", data={"csrf": _csrf(client)})

    phone = client.application.test_client()
    _ask(phone, me)
    _use(phone, _link(outbox))
    with phone.session_transaction() as s:
        assert s["profile"]["nace"] == "10.71"


# ------------------------------------------------------------------ the guards


def test_no_password_anywhere():
    """The roadmap's acceptance, held: no password field in any template."""
    for page in TEMPLATES.rglob("*.html"):
        assert 'type="password"' not in page.read_text(encoding="utf-8"), page.name


def test_production_refuses_the_development_secret():
    with pytest.raises(ValueError, match="real secret"):
        load_settings(env="production")


def test_production_sends_nothing_without_a_mail_server():
    settings = load_settings(env="production", secret_key="x" * 40)
    with pytest.raises(mail.MailNotConfigured):
        mail.send(settings, "proba@example.test", "Тест", "тело")


def test_the_mail_is_plain_macedonian_text(tmp_path):
    settings = load_settings(env="testing", outbox_dir=str(tmp_path))
    mail.send(settings, "proba@example.test", "Линк за најава", "Здраво")
    message = email.message_from_bytes(next(tmp_path.glob("*.eml")).read_bytes())
    subject = "".join(
        t.decode(c or "utf-8") if isinstance(t, bytes) else t
        for t, c in decode_header(message["Subject"])
    )
    assert subject == "Линк за најава" and message.get_content_type() == "text/plain"
