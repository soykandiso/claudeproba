"""The shortlist at `/povici`, and the cited passage behind each condition (P2 s28).

The first screen that shows a customer what the matching engine says. It reads the
profile `/profil` left in the session, runs `app/matching/shortlist.build`, and
renders it. It decides nothing: verdicts are stage 1's, the order is stage 2's, and
the citation check is the shortlist module's.

**Every condition links to its words.** `/povici/izvor/<criterion>` shows the
quoted passage inside a short window of the stored text around it, with the
official source and the date we read it. A window, not the whole document: the
reuse of official publications is P3 s43's question, and a short excerpt with a
link to the original is the conservative answer until then.
"""

import uuid

from flask import Blueprint, abort, redirect, render_template, url_for
from sqlalchemy import select

from app.config import load_settings
from app.db import session_factory
from app.matching import intake, shortlist
from app.models import Call, EligibilityCriterion, Programme, RawSnapshot
from app.web.intake import profile as current_profile

bp = Blueprint("shortlist", __name__, url_prefix="/povici")

# Characters of stored text shown either side of a quote on the passage page.
CONTEXT = 600

SCORE_LABELS = {
    "sector_fit": "Дејност",
    "size_fit": "Износ",
    "timeline_fit": "Рок",
    "cofinancing_fit": "Сопствено учество",
    "soft_criteria": "Предности",
    "semantic_fit": "Опис на проектот",
}


def _summary(profile) -> str:
    """The profile in one sentence, in the demo's words: who, what, where, how big."""
    parts = [
        intake.entity_label(profile),
        f"дејност {profile.nace_code}" if profile.nace_code else None,
        intake.municipality_label(profile),
        f"основана {profile.answers['founded']}" if profile.answers.get("founded") else None,
        f"{intake.employees_label(profile)} вработени" if intake.employees_label(profile) else None,
    ]
    return ", ".join(p for p in parts if p)


def _sessions():
    return session_factory(load_settings())


@bp.get("/")
def index():
    profile = current_profile()
    if profile is None:
        return redirect(url_for("intake.form"))
    with _sessions()() as session:
        result = shortlist.build(session, profile)
        return render_template(
            "shortlist/index.html",
            profile=profile,
            result=result,
            summary=_summary(profile),
            score_labels=SCORE_LABELS,
        )


@bp.get("/izvor/<uuid:criterion_id>")
def passage(criterion_id: uuid.UUID):
    with _sessions()() as session:
        row = session.execute(
            select(EligibilityCriterion, RawSnapshot, Call, Programme.institution)
            .join(RawSnapshot, RawSnapshot.id == EligibilityCriterion.snapshot_id)
            .join(Call, Call.id == EligibilityCriterion.call_id)
            .join(Programme, Programme.id == Call.programme_id)
            .where(
                EligibilityCriterion.id == criterion_id,
                EligibilityCriterion.is_approved.is_(True),
                Call.is_published.is_(True),
            )
        ).first()
        if row is None:
            abort(404)
        criterion, snapshot, call, institution = row
        text = snapshot.normalised_text or ""
        start, end = criterion.quote_start, criterion.quote_end
        # The same check the shortlist makes: a passage that is not where the
        # citation says is not shown as the source of anything.
        if start is None or end is None or text[start:end] != criterion.source_quote:
            abort(404)
        lo, hi = max(0, start - CONTEXT), min(len(text), end + CONTEXT)
        return render_template(
            "shortlist/passage.html",
            criterion=criterion,
            call=call,
            institution=institution,
            snapshot=snapshot,
            source_url=criterion.source_url or snapshot.url,
            before=("…" if lo else "") + text[lo:start],
            quoted=text[start:end],
            after=text[end:hi] + ("…" if hi < len(text) else ""),
        )
