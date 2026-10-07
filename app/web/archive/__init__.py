"""The public archive at `/arhiva` (roadmap P3 s41–42): programmes and their calls,
open and closed, for whoever arrives from a search engine.

Everything here follows `docs/legal-notes.md` §3. A page is our words (the call's facts,
the conditions as a reviewer approved them) with each condition's own words as a short
verbatim quote, found again in the stored text before it is shown (invariant 2), its
source, its date and the credit its licence asks for, and a link to the original. No full
text, no mirrored document, no contact person. Manual entries are left out: their text
belongs to whoever wrote it (legal-notes §5, the conservative default of 07.10.2026).

A closed call stays: "what did this programme fund last year, and when did it close" is
the question that brings people here, and it is the one a ministry's site answers worst.
"""

import datetime as dt
import uuid
from itertools import groupby

from flask import Blueprint, abort, current_app, render_template
from sqlalchemy import func, select

from app.config import load_settings
from app.db import session_factory
from app.matching import shortlist
from app.models import Call, EligibilityCriterion, Programme, SourceFeed
from app.models.enums import CallStatus

bp = Blueprint("archive", __name__, url_prefix="/arhiva")

# Never in the public archive: text that is somebody's copyright (legal-notes §2).
EXCLUDED_SOURCES = ("manual",)


def _sessions():
    return session_factory(load_settings())


def _public():
    """Published calls from sources the archive may quote."""
    return (
        Call.is_published.is_(True),
        Call.status.notin_([CallStatus.DRAFT, CallStatus.CANCELLED]),
        SourceFeed.slug.notin_(EXCLUDED_SOURCES),
    )


def state(call: Call, now: dt.datetime | None = None) -> str:
    """open, announced or closed: what a reader needs before anything else."""
    now = now or dt.datetime.now(dt.UTC)
    if call.status == CallStatus.CLOSED or (call.deadline_at and call.deadline_at <= now):
        return "closed"
    if call.status == CallStatus.ANNOUNCED:
        return "announced"
    return "open"


def _indexable() -> bool:
    # Search engines are let in once the site is the real one (P0.5 s4); until then
    # every page says noindex, as the rest of the site does.
    return current_app.extensions["settings"].is_production


@bp.get("/")
def index():
    with _sessions()() as session:
        rows = session.execute(
            select(
                Programme.slug,
                Programme.name_mk,
                Programme.institution,
                func.count(Call.id),
                func.max(Call.deadline_at),
            )
            .join(Call, Call.programme_id == Programme.id)
            .join(SourceFeed, SourceFeed.id == Call.source_feed_id)
            .where(*_public())
            .group_by(Programme.slug, Programme.name_mk, Programme.institution)
            .order_by(Programme.institution, Programme.name_mk)
        ).all()
    institutions = [(name, list(group)) for name, group in groupby(rows, key=lambda r: r[2])]
    return render_template("archive/index.html", institutions=institutions, indexable=_indexable())


@bp.get("/<slug>/")
def programme(slug: str):
    with _sessions()() as session:
        found = session.scalar(select(Programme).where(Programme.slug == slug))
        if found is None:
            abort(404)
        calls = session.scalars(
            select(Call)
            .join(SourceFeed, SourceFeed.id == Call.source_feed_id)
            .where(Call.programme_id == found.id, *_public())
            .order_by(Call.deadline_at.desc().nullsfirst(), Call.title_mk)
        ).all()
    if not calls:
        abort(404)
    now = dt.datetime.now(dt.UTC)
    return render_template(
        "archive/programme.html",
        programme=found,
        calls=[(c, state(c, now)) for c in calls],
        indexable=_indexable(),
    )


@bp.get("/<slug>/<uuid:call_id>")
def call(slug: str, call_id: uuid.UUID):
    with _sessions()() as session:
        row = session.execute(
            select(Call, Programme)
            .join(Programme, Programme.id == Call.programme_id)
            .join(SourceFeed, SourceFeed.id == Call.source_feed_id)
            .where(Call.id == call_id, Programme.slug == slug, *_public())
        ).first()
        if row is None:
            abort(404)
        found, prog = row
        criteria = session.scalars(
            select(EligibilityCriterion)
            .where(
                EligibilityCriterion.call_id == found.id,
                EligibilityCriterion.is_approved.is_(True),
            )
            .order_by(EligibilityCriterion.quote_start, EligibilityCriterion.id)
        ).all()
        cited = shortlist.verified(session, list(criteria))
    # A condition whose words cannot be found again is not shown as a condition here:
    # the archive states nothing it cannot cite (invariant 2).
    conditions = [(c, cited[c.id]) for c in criteria if c.id in cited]
    return render_template(
        "archive/call.html",
        call=found,
        programme=prog,
        state=state(found),
        conditions=conditions,
        uncited=len(criteria) - len(conditions),
        indexable=_indexable(),
    )
