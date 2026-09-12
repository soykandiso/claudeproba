import pytest

from app import create_app
from app.config import load_settings


@pytest.fixture
def app():
    return create_app(load_settings(env="testing", version="test"))


@pytest.fixture
def client(app):
    return app.test_client()
