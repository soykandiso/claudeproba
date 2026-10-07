"""The terms, the privacy policy and the processors, on the site (roadmap P3 s45).

`/uslovi` and `/privatnost` show the current version; `/uslovi/<version>` an earlier one,
because a person accepted that exact text and may want to read it again. A version with
no template is a 404, never the current text under an old date.
"""

import re

import click
from flask import Blueprint, abort, render_template, url_for
from flask.cli import AppGroup
from jinja2 import TemplateNotFound
from markupsafe import Markup, escape

from app.legal import legal

bp = Blueprint("legal", __name__)

PLACEHOLDER = Markup("<strong>[се утврдува]</strong>")


def _entity(field: str) -> Markup:
    value = getattr(legal().entity, field)
    return escape(value) if value else PLACEHOLDER


def _render(kind: str, version: str, current_endpoint: str):
    # A version is a date; anything else is not a file to look for.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", version):
        abort(404)
    try:
        return render_template(
            f"legal/{kind}/{version}.html",
            legal=legal(),
            entity=_entity,
            shown_version=version,
            current_url=url_for(current_endpoint),
        )
    except TemplateNotFound:
        abort(404)


@bp.get("/uslovi")
def terms():
    return _render("terms", legal().version, "legal.terms")


@bp.get("/uslovi/<version>")
def terms_version(version: str):
    return _render("terms", version, "legal.terms")


@bp.get("/privatnost")
def privacy():
    return _render("privacy", legal().version, "legal.privacy")


@bp.get("/privatnost/<version>")
def privacy_version(version: str):
    return _render("privacy", version, "legal.privacy")


@bp.get("/obrabotuvachi")
def processors():
    return render_template("legal/processors.html", legal=legal())


# ------------------------------------------------------------------ the launch check

cli = AppGroup("legal", help="The legal texts (docs/runbook.md: run before every deploy).")


@cli.command("check")
def check():
    """Fail while the terms or the privacy policy would show a placeholder."""
    gaps = legal().missing()
    for gap in gaps:
        click.echo(f"not yet decided: {gap}")
    if gaps:
        raise SystemExit(1)
    click.echo(f"legal texts complete, version {legal().version}")
