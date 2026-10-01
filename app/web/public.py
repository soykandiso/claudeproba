"""Public pages.

Currently one placeholder so there is something to look at while the platform is
being built. This is NOT the landing page -- that is P3, and it follows the
design system in .claude/skills/design-system/SKILL.md. Nothing here should be
treated as a design decision.
"""

from flask import Blueprint, current_app, render_template

bp = Blueprint("public", __name__)


@bp.get("/")
def index():
    settings = current_app.extensions["settings"]
    return render_template("index.html", settings=settings)
