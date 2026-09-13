"""Flask application factory."""

from flask import Flask

from app.config import Settings, load_settings


def create_app(settings: Settings | None = None) -> Flask:
    # Templates and static files live under app/web/, next to the blueprints that
    # use them, rather than at the package root where Flask looks by default.
    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
    )

    settings = settings or load_settings()
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["DEBUG"] = settings.debug
    app.config["TESTING"] = settings.env == "testing"

    # Kept as the single source of truth for configuration. Flask's own config dict
    # stays limited to the keys Flask itself reads, so there is one place to look.
    app.extensions["settings"] = settings

    # Templates are re-read on every request outside production, so an edit to a
    # page shows up on refresh without restarting anything.
    app.config["TEMPLATES_AUTO_RELOAD"] = not settings.is_production

    from app.web.health import bp as health_bp
    from app.web.public import bp as public_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(public_bp)

    # Invented calls and citations; must never be reachable in production.
    if not settings.is_production:
        from app.web.demo import bp as demo_bp

        app.register_blueprint(demo_bp)

    from app.cli import register_cli

    register_cli(app)

    if settings.live_reload:
        from app.web import devreload

        devreload.init_app(app)

    return app
