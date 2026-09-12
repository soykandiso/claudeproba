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
    monkeypatch.setenv("GRANTS_SECRET_KEY", "from-environment")

    settings = load_settings()

    assert settings.is_production is True
    assert settings.secret_key == "from-environment"
