"""The public surface: the landing page and the prices (roadmap P3 s38–39).

Both say only what the platform does today. The landing's example condition is a real
one, its quote found again in the stored text before it is shown (invariant 2); with
none to show, the section is left out rather than filled with an invented one. Prices
come from `config/prices.yaml` (docs/decisions.md D1), never from the template.
"""

from flask import Blueprint, current_app, redirect, render_template, url_for
from sqlalchemy.exc import SQLAlchemyError

from app.config import load_settings
from app.db import session_factory
from app.matching import shortlist
from app.pricing import prices

bp = Blueprint("public", __name__)


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
