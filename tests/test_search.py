"""What search engines see (roadmap P3 s46): robots.txt, the sitemap, the robots tags and
the structured data of the archive."""

import json
import re

import pytest

from app import create_app
from app.config import load_settings
from app.web import archive, public
from tests.test_archive import _slug
from tests.test_archive import served as served  # noqa: F401 (fixture)
from tests.test_shortlist import FITS, db, make_call, registry  # noqa: F401 (fixture)


@pytest.fixture
def production():
    return create_app(load_settings(env="production", secret_key="x" * 40)).test_client()


def test_nothing_is_crawled_outside_production(client):
    assert client.get("/robots.txt").get_data(as_text=True) == "User-agent: *\nDisallow: /\n"


def test_production_keeps_out_what_is_a_visitors_own(production):
    robots = production.get("/robots.txt").get_data(as_text=True)
    for path in public.PRIVATE:
        assert f"Disallow: {path}\n" in robots
    assert "Allow: /\n" in robots and "Sitemap: http://localhost/sitemap.xml" in robots


def test_public_pages_open_themselves_only_in_production(client, production, monkeypatch):
    monkeypatch.setattr(public, "_sample", lambda: None)
    for path in ("/", "/ceni", "/uslovi", "/privatnost", "/obrabotuvachi"):
        assert '<meta name="robots" content="noindex">' in client.get(path).get_data(as_text=True)
        assert 'content="index, follow"' in production.get(path).get_data(as_text=True), path
    # A visitor's own pages never do.
    for path in ("/profil/", "/najava"):
        assert 'content="index, follow"' not in production.get(path).get_data(as_text=True), path


@db
def test_the_sitemap_lists_the_public_pages_and_the_archive(client, served):  # noqa: F811
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, title="Повик за мапата", criteria=[FITS])
        s.commit()
        slug = _slug(s, call)
    xml = client.get("/sitemap.xml")
    body = xml.get_data(as_text=True)
    assert xml.mimetype == "application/xml"
    for path in ("/", "/ceni", "/arhiva/", "/uslovi", "/privatnost"):
        assert f"<loc>http://localhost{path}</loc>" in body, path
    assert f"/arhiva/{slug}/{call.id}</loc>" in body and f"/arhiva/{slug}/</loc>" in body
    assert "/profil" not in body and "/povici" not in body


@db
def test_a_call_page_says_its_facts_to_search_engines(client, served):  # noqa: F811
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, title="Повик </script>", criteria=[FITS])
        call.grant_max_mkd = 300000
        s.commit()
        slug = _slug(s, call)
    page = client.get(f"/arhiva/{slug}/{call.id}").get_data(as_text=True)
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
    assert "</script>" not in raw  # a title cannot close the tag
    data = json.loads(raw)
    assert data["@type"] == "MonetaryGrant" and data["name"] == "Повик </script>"
    assert data["amount"] == {"@type": "MonetaryAmount", "currency": "MKD", "maxValue": 300000.0}
    assert data["sameAs"] == call.canonical_url
    assert archive  # the module under test
