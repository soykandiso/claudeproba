"""Flask application factory."""

import datetime as dt

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
    # Forms that change data also carry a CSRF token (app/web/admin); Lax keeps the
    # session cookie off cross-site POSTs as a second line.
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # The largest thing anyone posts is a тековна состојба (P3, app/matching/tekovna.py).
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024

    # Kept as the single source of truth for configuration. Flask's own config dict
    # stays limited to the keys Flask itself reads, so there is one place to look.
    app.extensions["settings"] = settings

    # Templates are re-read on every request outside production, so an edit to a
    # page shows up on refresh without restarting anything.
    app.config["TEMPLATES_AUTO_RELOAD"] = not settings.is_production

    from app import i18n
    from app.web import format

    # Which language a page is in, and _() in every template (app/i18n.py, P3 s40).
    i18n.init(app)
    # Dates, amounts and verdict words, the same on every screen (app/web/format.py).
    format.register(app)

    from app.web.account import bp as account_bp
    from app.web.account import current_account_id
    from app.web.archive import bp as archive_bp
    from app.web.health import bp as health_bp
    from app.web.intake import bp as intake_bp
    from app.web.legal import bp as legal_bp
    from app.web.legal import cli as legal_cli
    from app.web.public import bp as public_bp
    from app.web.shortlist import bp as shortlist_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(public_bp)
    # The intake form and the shortlist are real customer screens, registered everywhere.
    app.register_blueprint(intake_bp)
    app.register_blueprint(shortlist_bp)
    # The public archive of programmes and calls, open and closed (P3 s41–42).
    app.register_blueprint(archive_bp)
    # Sign-in by e-mail link, the account and its saved profiles (P3 s44). A signed-in
    # browser stays signed in for 30 days; signing out clears it at once.
    app.register_blueprint(account_bp)
    # The terms, the privacy policy and the processors, versioned (P3 s45).
    app.register_blueprint(legal_bp)
    app.cli.add_command(legal_cli)
    # Erasure, export and the 24-month retention job (app/accounts.py).
    from app.accounts import cli as accounts_cli

    app.cli.add_command(accounts_cli)
    # Proformas: the launch check and a sample for the accountant (app/orders/proforma.py).
    from app.orders.proforma import cli as invoices_cli

    app.cli.add_command(invoices_cli)
    app.config["PERMANENT_SESSION_LIFETIME"] = dt.timedelta(days=30)
    app.add_template_global(lambda: bool(current_account_id()), "signed_in")

    # Invented calls and citations; must never be reachable in production.
    if not settings.is_production:
        from app.web.demo import bp as demo_bp

        app.register_blueprint(demo_bp)

    # Every design token rendered, for whoever builds screens (DS2). Not a customer page.
    if not settings.is_production:
        from app.web.style import bp as stil_bp

        app.register_blueprint(stil_bp)

    # Publishes calls, and there is no operator sign-in yet (docs/decisions.md D11).
    if not settings.is_production:
        from app.web.admin import bp as admin_bp

        app.register_blueprint(admin_bp)

    from app.cli import register_cli

    register_cli(app)

    if settings.live_reload:
        from app.web import devreload

        devreload.init_app(app)

    return app
