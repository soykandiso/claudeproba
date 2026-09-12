"""Flask application factory."""

from flask import Flask

from app.config import Settings, load_settings


def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__)

    settings = settings or load_settings()
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["DEBUG"] = settings.debug
    app.config["TESTING"] = settings.env == "testing"

    # Kept as the single source of truth for configuration. Flask's own config dict
    # stays limited to the keys Flask itself reads, so there is one place to look.
    app.extensions["settings"] = settings

    from app.web.health import bp as health_bp

    app.register_blueprint(health_bp)

    return app
