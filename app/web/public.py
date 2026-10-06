"""Public pages.

Currently one placeholder so there is something to look at while the platform is
being built. This is NOT the landing page -- that is P3, and it follows the
design system in .claude/skills/design-system/SKILL.md. Nothing here should be
treated as a design decision.
"""

from flask import Blueprint, current_app, redirect, render_template, url_for

bp = Blueprint("public", __name__)


@bp.get("/")
def index():
    settings = current_app.extensions["settings"]
    return render_template("index.html", settings=settings)


@bp.get("/favicon.ico")
def favicon():
    # Browsers ask for this path on any page without an icon link (the report's document
    # view is the PDF's template and has none); the one icon is the SVG (DL7).
    return redirect(url_for("static", filename="favicon.svg"), code=301)
