"""The intake form at `/profil` (roadmap P2 s23).

The first real customer screen in the codebase: everything before it was either an
operator tool or the demo. It asks the questions in `app/matching/intake.py`,
renders the bands and lists `app/matching/normalise.py` and `data/` establish, and
hands the answers to stage 0. It decides nothing itself.

**The answers live in the signed session cookie, not in a row.** `applicant_profile`
needs an `account_id` and there are no accounts yet (docs/decisions.md D11, magic
link at P3 s44), so a profile here belongs to a browser. That is also the honest
default: nothing is stored about a visitor who never orders anything. The order
flow is the moment that changes, and it is P4's to change.

**HTMX carries exactly one thing: the activity picker.** A thousand НКД classes
cannot be a `<select>` on a phone, and asking people to know their code is how the
field gets left empty. Everything else is a plain form that posts — which is also
what the picker degrades to with JavaScript off, since `resolve_nace` takes a typed
code as readily as a chosen one.
"""

import time

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.ai.scrub import Scrubber
from app.matching import intake, reference
from app.matching.normalise import Profile, normalise
from app.web import csrf

bp = Blueprint("intake", __name__, url_prefix="/profil")
csrf.protect(bp)

ANSWERS = "profile"
STARTED = "profile_started"
SEARCH_LIMIT = 8
UNKNOWN = "Не е одговорено"


def answers() -> dict | None:
    return session.get(ANSWERS)


def profile() -> Profile | None:
    stored = answers()
    return normalise(stored) if stored else None


# ------------------------------------------------------------------- the form


def _duration_words(seconds: int | None) -> str | None:
    """«2 минути и 14 секунди»: the s23/DS4 acceptance is under three minutes, and a
    person reading the page should not have to divide by sixty to know."""
    if not seconds:
        return None
    minutes, rest = divmod(int(seconds), 60)
    parts = []
    if minutes:
        parts.append("1 минута" if minutes == 1 else f"{minutes} минути")
    if rest or not minutes:
        parts.append("1 секунда" if rest == 1 else f"{rest} секунди")
    return " и ".join(parts)


def _error_items(errors: dict[str, str]) -> list[tuple[str, str]]:
    """(field id, what to fix) in the order the form asks, for the summary's links.

    Each question's key is its control's id, so a link lands on the control itself.
    """
    return [
        (q.key, f"{q.label_mk}: {errors[q.key]}")
        for _title, rows in intake.sections()
        for q in rows
        if q.key in errors
    ]


def _context(posted: dict, errors: dict[str, str]) -> dict:
    return {
        "sections": intake.sections(),
        "a": posted,
        "errors": errors,
        "error_items": _error_items(errors),
        "chosen_nace": reference.resolve_nace(posted.get("nace")),
    }


@bp.get("/")
def form():
    # When the form was opened, so a completed intake can be timed against the
    # roadmap's acceptance ("under 3 minutes") instead of being asserted.
    session.setdefault(STARTED, time.time())
    return render_template("intake/form.html", **_context(answers() or {}, {}))


@bp.post("/")
def save():
    posted, errors = intake.clean(request.form)
    if errors:
        return render_template("intake/form.html", **_context(posted, errors)), 422
    session[ANSWERS] = posted
    session["profile_seconds"] = round(time.time() - session.pop(STARTED, time.time()))
    return redirect(url_for("intake.review"))


@bp.get("/dejnosti")
def activities():
    """The activity picker: `?q=` lists matches, `?pick=` puts one in the field.

    Two swaps rather than a line of JavaScript to write a value into an input:
    picking re-renders the whole field, which is also what makes the chosen
    activity's full name appear under it.
    """
    picked = request.args.get("pick", "")
    if picked:
        entry = reference.resolve_nace(picked)
        value = f"{entry.code} {entry.name_mk}" if entry else ""
        return render_template(
            "intake/_activity.html",
            q=intake.question("nace"),
            a={"nace": value},
            errors={},
            chosen_nace=entry,
            results=None,
        )
    query = request.args.get("nace", "").strip()
    return render_template(
        "intake/_results.html",
        query=query,
        results=reference.search_nace(query, limit=SEARCH_LIMIT) if len(query) > 1 else [],
    )


@bp.get("/pregled")
def review():
    p = profile()
    if p is None:
        return redirect(url_for("intake.form"))
    return render_template(
        "intake/review.html",
        profile=p,
        rows=intake.describe(p),
        # (label, what it was read as, no link) for the grouped list (DL3).
        answers=[(label, value or UNKNOWN, None) for label, value in intake.describe(p)],
        unknown=UNKNOWN,
        scrubbed=Scrubber().scrub(p.project_description),
        took=_duration_words(session.get("profile_seconds")),
    )
