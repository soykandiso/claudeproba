import os

import pytest
from pydantic import ValidationError

from app import create_app
from app.config import load_settings


@pytest.fixture
def live_client():
    app = create_app(load_settings(env="development", version="test", live_reload=True))
    return app.test_client()


def test_off_by_default(client):
    assert client.get("/__dev/reload").status_code == 404
    assert "/__dev/reload" not in client.get("/").get_data(as_text=True)


def test_refused_in_production():
    with pytest.raises(ValidationError):
        load_settings(env="production", live_reload=True)


def test_pages_get_the_script_before_body_close(live_client):
    body = live_client.get("/").get_data(as_text=True)

    assert body.index("/__dev/reload") < body.index("</body>")


def test_json_responses_are_left_alone(live_client):
    assert "<script>" not in live_client.get("/healthz").get_data(as_text=True)


def test_token_changes_when_a_template_changes(live_client, tmp_path):
    app = live_client.application
    app.template_folder = str(tmp_path)
    page = tmp_path / "page.html"
    page.write_text("one")
    first = live_client.get("/__dev/reload").get_json()["token"]

    page.write_text("two")
    stat = page.stat()
    os.utime(page, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert live_client.get("/__dev/reload").get_json()["token"] != first
