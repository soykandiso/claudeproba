"""The public surface: the landing page and the prices (roadmap P3 s38–39).

Both say only what the platform does today. The landing's example condition is a real
one, its quote found again in the stored text before it is shown (invariant 2); with
none to show, the section is left out rather than filled with an invented one. Prices
come from `config/prices.yaml` (docs/decisions.md D1), never from the template.
"""

from flask import Blueprint, Response, current_app, redirect, render_template, url_for
from markupsafe import Markup
from sqlalchemy.exc import SQLAlchemyError

from app.config import load_settings
from app.db import session_factory
from app.matching import shortlist
from app.pricing import prices
from app.web import archive

bp = Blueprint("public", __name__)


@bp.app_template_global()
def price_list():
    """config/prices.yaml for any template (the shortlist's order card, P4 s50)."""
    return prices()


@bp.app_template_global()
def robots_meta() -> Markup:
    """The robots tag of a public page: indexed on the real site only (P3 s46).

    Private pages (the form, the shortlist, the account, the admin) never call this and
    keep the shell's noindex.
    """
    indexed = current_app.extensions["settings"].is_production
    return Markup(f'<meta name="robots" content="{"index, follow" if indexed else "noindex"}">')


def _sample():
    # The landing must render without a database: a page that explains the service is
    # the one page that cannot be down because the registry is.
    try:
        with session_factory(load_settings())() as session:
            return shortlist.sample(session)
    except SQLAlchemyError:
        current_app.logger.warning("landing: no sample, the database is not reachable")
        return None


@bp.get("/")
def index():
    return render_template(
        "index.html",
        sample=_sample(),
        prices=prices(),
    )


@bp.get("/ceni")
def pricing():
    return render_template("pricing.html", prices=prices())


@bp.get("/favicon.ico")
def favicon():
    # Browsers ask for this path on any page without an icon link (the report's document
    # view is the PDF's template and has none); the one icon is the SVG (DL7).
    return redirect(url_for("static", filename="favicon.svg"), code=301)


# ------------------------------------------------------------------ search engines (P3 s46)

# Never crawled, on any site: the form and what follows from it are a visitor's own, the
# account is personal, the admin and the demo are not for the public.
PRIVATE = ("/profil", "/povici", "/smetka", "/najava", "/odjava", "/admin", "/demo", "/stil")


@bp.get("/robots.txt")
def robots_txt():
    if not current_app.extensions["settings"].is_production:
        lines = ["User-agent: *", "Disallow: /"]
    else:
        lines = ["User-agent: *", *(f"Disallow: {path}" for path in PRIVATE), "Allow: /"]
        lines.append(f"Sitemap: {url_for('public.sitemap', _external=True)}")
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@bp.get("/sitemap.xml")
def sitemap():
    """The public pages and the archive, with the date each call was last checked."""
    pages = [
        (url_for("public.index", _external=True), None),
        (url_for("public.pricing", _external=True), None),
        (url_for("archive.index", _external=True), None),
        (url_for("legal.terms", _external=True), None),
        (url_for("legal.privacy", _external=True), None),
        (url_for("legal.processors", _external=True), None),
    ]
    try:
        with archive._sessions()() as session:
            pages += archive.sitemap_entries(session)
    except SQLAlchemyError:
        current_app.logger.warning("sitemap: the archive is not reachable, listing the rest")
    return Response(render_template("sitemap.xml", pages=pages), mimetype="application/xml")
