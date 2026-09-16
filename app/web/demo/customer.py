"""Customer screens: landing, intake, shortlist, report preview, source, account, alerts."""

from flask import abort, redirect, render_template, request, url_for

from app.models.enums import Verdict
from app.web.demo import bp, engine, store
from app.web.demo.data import PURPOSES, by_snapshot


def current_profile() -> engine.Profile | None:
    answers = store.answers()
    return engine.normalise(answers) if answers else None


@bp.get("/")
def landing():
    call = store.find_call("fitr-novoosnovani")
    criterion = call.criteria[0]
    return render_template(
        "demo/landing.html", sample_label=criterion.label, sample=call.citation(criterion)
    )


@bp.get("/vodic")
def guide():
    return render_template("demo/guide.html")


@bp.post("/reset")
def reset():
    store.reset()
    return redirect(url_for("demo.guide"))


def _intake_context(answers, errors):
    return {
        "a": answers,
        "errors": errors,
        "entity_forms": engine.ENTITY_FORMS,
        "municipalities": engine.MUNICIPALITIES,
        "employees": engine.EMPLOYEES,
        "turnover": engine.TURNOVER,
        "amounts": engine.AMOUNTS,
        "timelines": engine.TIMELINES,
        "purposes": PURPOSES,
        "nace_examples": engine.NACE_EXAMPLES,
    }


@bp.route("/profil", methods=["GET", "POST"])
def intake():
    if request.method == "POST":
        answers, errors = engine.clean_answers(request.form)
        if errors:
            return render_template("demo/intake.html", **_intake_context(answers, errors)), 422
        store.save_answers(answers)
        return redirect(url_for("demo.shortlist"))
    answers = store.answers() or engine.DEFAULT_ANSWERS
    return render_template("demo/intake.html", **_intake_context(answers, {}))


@bp.post("/primer-profil")
def sample_profile():
    store.save_answers(dict(engine.DEFAULT_ANSWERS))
    return redirect(url_for("demo.shortlist"))


@bp.get("/lista")
def shortlist():
    profile = current_profile()
    if profile is None:
        return render_template("demo/shortlist_empty.html")
    matches = engine.shortlist(store.published_calls(), profile)
    version, _ = engine.weights()
    return render_template(
        "demo/shortlist.html",
        profile=profile,
        open_matches=[m for m in matches if m.verdict != Verdict.NOT_ELIGIBLE][:10],
        excluded=[m for m in matches if m.verdict == Verdict.NOT_ELIGIBLE],
        shape=engine.applicant_shape(profile),
        scrubbed=engine.scrubbed_description(profile),
        weights_version=version,
    )


@bp.get("/izvestaj/<slug>")
def report(slug: str):
    call = next((c for c in store.published_calls() if c.slug == slug), None)
    if call is None:
        abort(404)
    profile = current_profile() or engine.normalise(engine.DEFAULT_ANSWERS)
    return render_template(
        "demo/report.html",
        m=engine.match(call, profile),
        profile=profile,
        order=None,
        sample_profile=store.answers() is None,
    )


@bp.get("/izvor/<snapshot_id>")
def source(snapshot_id: str):
    call = by_snapshot(snapshot_id)
    if call is None:
        abort(404)
    text = call.document_text
    start = request.args.get("od", type=int)
    end = request.args.get("do", type=int)
    if start is None or end is None or not 0 <= start < end <= len(text):
        start = end = None
    return render_template(
        "demo/source.html",
        call=call,
        before=text[:start] if start is not None else text,
        quoted=text[start:end] if start is not None else "",
        after=text[end:] if end is not None else "",
        start=start,
        end=end,
    )


@bp.get("/smetka")
def account():
    profile = current_profile()
    calls = {c.slug: c for c in store.all_calls()}
    return render_template(
        "demo/account.html",
        profile=profile,
        orders=store.orders(),
        calls=calls,
        products=store.PRODUCTS,
        sub=store.subscription(),
    )


@bp.route("/sledenje", methods=["GET", "POST"])
def monitoring():
    if request.method == "POST":
        if request.form.get("action") == "cancel":
            store.unsubscribe()
        elif request.form.get("frequency") in ("instant", "weekly"):
            store.subscribe(request.form["frequency"])
        return redirect(url_for("demo.monitoring"))

    profile = current_profile()
    alerts = []
    if profile and store.subscription():
        # New calls reach subscribers only after review publishes them (P6 s69).
        newly = [c for c in store.published_calls() if not c.published]
        alerts = [
            m
            for m in (engine.match(c, profile) for c in newly)
            if m.verdict != Verdict.NOT_ELIGIBLE
        ]
    return render_template(
        "demo/monitoring.html", profile=profile, sub=store.subscription(), alerts=alerts
    )
