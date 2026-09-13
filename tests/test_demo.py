import pytest

from app import create_app
from app.config import load_settings

PAGES = ["/demo/", "/demo/profil", "/demo/lista", "/demo/izvestaj/fitr-novoosnovani"]
BANNED = ["гарантирано", "guaranteed", "approved", "you will receive", "одобрено"]


@pytest.mark.parametrize("path", PAGES)
def test_demo_pages_render_in_macedonian_with_demo_notice(client, path):
    body = client.get(path).get_data(as_text=True)

    assert 'lang="mk"' in body
    assert "Демо верзија" in body
    for word in BANNED:
        assert word not in body.lower()


def test_unknown_report_is_404(client):
    assert client.get("/demo/izvestaj/ne-postoi").status_code == 404


def test_demo_is_not_registered_in_production():
    """Invented calls and citations must never be publicly reachable."""
    app = create_app(load_settings(env="production", version="test", secret_key="x" * 40))

    assert "demo" not in app.blueprints


def test_dates_are_dd_mm_yyyy(client):
    body = client.get("/demo/lista").get_data(as_text=True)

    import re

    assert re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", body)
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", body)
