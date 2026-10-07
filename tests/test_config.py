import pytest
from pydantic import ValidationError

from app.config import load_settings


def test_defaults_are_development():
    settings = load_settings()

    assert settings.env == "development"
    assert settings.is_production is False
    assert settings.default_language == "mk"
    assert settings.timezone == "Europe/Skopje"


def test_env_is_constrained_to_known_values():
    """Config is validated at boot so a typo fails the process, not a request."""
    with pytest.raises(ValidationError):
        load_settings(env="prod")


def test_reads_environment(monkeypatch):
    monkeypatch.setenv("GRANTS_ENV", "production")
    monkeypatch.setenv("GRANTS_SECRET_KEY", "from-environment-" + "s" * 32)

    settings = load_settings()

    assert settings.is_production is True
    assert settings.secret_key.startswith("from-environment-")


def test_sqlalchemy_url_is_dialect_qualified():
    """psycopg takes the plain libpq URL; SQLAlchemy needs the +psycopg form."""
    settings = load_settings(database_url="postgresql://u:p@db:5432/grants")

    assert settings.sqlalchemy_url == "postgresql+psycopg://u:p@db:5432/grants"
