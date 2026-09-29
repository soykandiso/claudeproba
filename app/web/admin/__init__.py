"""The operator's review queue: extraction items (roadmap P1 s15) and reports (P2 s33).

Screens over app/review/extraction.py and app/review/report.py, which hold every
decision; nothing here decides. Forms post and redirect; no JavaScript.

**Not registered in production** (app/__init__.py) until the operator can sign in:
publishing a call is the most consequential action in the system, and there is no
authentication yet. How the operator signs in is docs/decisions.md D11.

Every POST carries a CSRF token from the session, so the forms are already safe
the day a login puts a cookie in front of them.
"""

import datetime as dt
import re
import uuid
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from markupsafe import Markup

from app.db import session_factory
from app.ingestion.normalise import NormaliseError, page_of
from app.ingestion.normalise.pdf import PAGE_IMAGE_TYPE, can_render_pages, render_page
from app.ingestion.snapshots import CorruptSnapshot, SnapshotStore
from app.ingestion.sources import manual
from app.matching.operators import FIELDS, Operator, ProfileField
from app.models import Call, RawSnapshot, SourceFeed
from app.models.enums import CriterionKind, ReviewState, TextSource, Verdict
from app.review import extraction as review
from app.review import report as reports
from app.web import csrf
from app.web.format import mkdate

bp = Blueprint("admin", __name__, url_prefix="/admin")

STAGE_LABELS = {
    review.APPROVE_CALL: "Повик за објава",
    review.NOT_A_CALL: "Моделот вели: не е јавен повик",
    review.EXTRACT: "Цитати што не се пронајдени дословно",
    review.INVALID_OUTPUT: "Одговорот на моделот не ја помина шемата",
    review.NORMALISE: "Документот не може да се прочита",
    review.MANUAL_ENTRY: "Рачен внес без повик за објава",
}

# A normalise item whose snapshot kept its text was read, with doubt: low OCR
# confidence (app/ingestion/normalise/snapshot.py). Extraction went ahead anyway.
READ_WITH_DOUBT = "Прочитано со OCR, со ниска сигурност"

MANUAL_OUTCOMES = {
    manual.FETCH_FAILED: "Адресите не можеа да се преземат.",
    manual.PROCESSING_FAILED: "Документите се преземени, но повикот не можеше да се обработи.",
    manual.ALREADY_KNOWN: "Ништо ново: овие документи веќе се повик или веќе чекаат преглед.",
}

STATE_LABELS = {
    ReviewState.PENDING: "Чека одлука",
    ReviewState.APPROVED: "Прифатено и објавено",
    ReviewState.EDITED: "Изменето и објавено",
    ReviewState.REJECTED: "Затворено",
}

KIND_LABELS = {
    CriterionKind.HARD_STRUCTURED: "Правило над профилот",
    CriterionKind.SOFT_SCORED: "Предност при рангирање",
    CriterionKind.NARRATIVE_VERIFY: "Проверка според текстот",
    CriterionKind.APPLICANT_ATTEST: "Го потврдува барателот",
    CriterionKind.DOCUMENTARY: "Документ во пријавата",
}

CITED_FIELD_LABELS = {
    "title_mk": "Наслов",
    "reference_code": "Број на повикот",
    "published_on": "Објавен",
    "opens_on": "Отворен од",
    "deadline": "Рок",
    "total_budget": "Вкупен буџет",
    "grant_min": "Најмалку по барател",
    "grant_max": "Најмногу по барател",
    "grant_share_pct": "Удел во трошоците",
}

_DAYS_IN_WORDS = {
    0: "истекува денес",
    1: "уште еден ден",
    2: "уште два дена",
    3: "уште три дена",
    4: "уште четири дена",
    5: "уште пет дена",
    6: "уште шест дена",
    7: "уште седум дена",
    8: "уште осум дена",
    9: "уште девет дена",
    10: "уште десет дена",
    11: "уште единаесет дена",
    12: "уште дванаесет дена",
    13: "уште тринаесет дена",
}


# -- request plumbing ---------------------------------------------------------------------


def _settings():
    return current_app.extensions["settings"]


def _tz() -> ZoneInfo:
    return ZoneInfo(_settings().timezone)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _store() -> SnapshotStore:
    """The raw bytes. Only the page image reads them; everything else reads text."""
    return SnapshotStore(_settings().snapshot_dir)


def _sessions():
    return session_factory(_settings())


csrf.protect(bp)


@bp.app_template_filter("date_mk")
def date_mk(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        value = value.astimezone(_tz())
    return value.strftime("%d.%m.%Y")


@bp.app_template_filter("datetime_mk")
def datetime_mk(value: dt.datetime | None) -> str:
    return value.astimezone(_tz()).strftime("%d.%m.%Y %H:%M") if value else ""


@bp.app_template_filter("iso_mkdate")
def iso_mkdate(value: str | None) -> str:
    """A stored ISO timestamp (a draft is JSON) as the Skopje day it fell on."""
    return mkdate(dt.datetime.fromisoformat(value)) if value else ""


@bp.app_template_filter("amount")
def amount(value) -> str:
    """12.000,00 as Macedonian writes it."""
    whole, _, cents = f"{float(value):,.2f}".partition(".")
    return f"{whole.replace(',', '.')},{cents}"


def _days_left(deadline: dt.datetime | None) -> str | None:
    if deadline is None:
        return None
    days = (deadline.astimezone(_tz()).date() - _now().astimezone(_tz()).date()).days
    if days < 0:
        return "рокот измина"
    return _DAYS_IN_WORDS.get(days)


_BLANK_LINES = re.compile(r"\n[ \t]*(?:\n[ \t]*)+")


def _in_context(text: str | None, start: int | None, end: int | None, radius: int = 160):
    """The passage around a citation with the quote marked, as stored in the snapshot."""
    if text is None or start is None or end is None:
        return None
    a, b = max(0, start - radius), min(len(text), end + radius)

    def lines(part: str) -> str:
        # Display only: blank lines between blocks cannot be quoted, and doubled they
        # spread a short passage over a screen. The slices themselves are untouched.
        return _BLANK_LINES.sub("\n", part)

    return Markup("{}{}<mark>{}</mark>{}{}").format(
        "…" if a else "",
        lines(text[a:start]),
        lines(text[start:end]),
        lines(text[end:b]),
        "…" if b < len(text) else "",
    )


def _item_or_404(db, item_id: int):
    item = review.get_item(db, item_id)
    if item is None:
        abort(404)
    return item


# -- screens ------------------------------------------------------------------------------


@bp.get("/")
def queue():
    with _sessions()() as db:
        pending, decided = review.queue(db)
        titles = _titles(db, pending + decided)
        report_pending, report_decided = reports.queue(db)
        return render_template(
            "admin/queue.html",
            pending=pending,
            decided=decided,
            report_pending=report_pending,
            report_decided=report_decided,
            report_titles={i.id: _report_title(i) for i in report_pending + report_decided},
            report_state_labels=REPORT_STATE_LABELS,
            titles=titles,
            stage_of=review.stage_of,
            stage_labels={item.id: _stage_label(db, item) for item in pending + decided},
            state_labels=STATE_LABELS,
        )


def _titles(db, items) -> dict[int, str]:
    """What each item is about, in words: the call title, else the document URL."""
    titles = {}
    for item in items:
        call = db.get(Call, item.call_id) if item.call_id else None
        payload = item.payload or {}
        extracted = (payload.get("extraction") or {}).get("title_mk") or {}
        titles[item.id] = (
            (call.title_mk if call else None)
            or extracted.get("value")
            or payload.get("public_url")
            or payload.get("url")
            or (payload.get("urls") or [None])[0]
            or item.reason
        )
    return titles


def _stage_label(db, item) -> str:
    stage = review.stage_of(item)
    if stage == review.NORMALISE:
        snapshot = db.get(RawSnapshot, (item.payload or {}).get("snapshot_id") or 0)
        if snapshot is not None and snapshot.normalised_text is not None:
            return READ_WITH_DOUBT
    return STAGE_LABELS.get(stage, stage)


def _page_image_url(snapshot: RawSnapshot | None, offset: int | None) -> dict | None:
    """Where to see the page a quote was read from, when that is a real question.

    Only OCR'd text raises it: `decisions.md` D9 rule 1 says a citation into OCR is
    verbatim against what the engine read, not against the paper, so the reviewer
    has to see the page before the quote can reach a customer. Text with a layer is
    the document's own characters and needs no photograph of itself.

    OCR runs on PDFs and nothing else (app/ingestion/normalise/pdf.py), so a page
    number is always meaningful here.
    """
    if snapshot is None or offset is None or not snapshot.normalised_text:
        return None
    if snapshot.text_source not in (TextSource.OCR, TextSource.MIXED):
        return None
    if not can_render_pages():  # a dev host without poppler: say nothing, show nothing
        return None
    page = page_of(snapshot.normalised_text, offset)
    return {
        "page": page,
        "url": url_for("admin.page_image", snapshot_id=snapshot.id, page=page),
    }


@bp.get("/dokument/<int:snapshot_id>/strana/<int:page>")
def page_image(snapshot_id: int, page: int):
    """The cited page of a stored document, rendered for a person to compare against.

    Rendered on demand from the bytes in the snapshot store and never written back:
    the source is content-addressed, so the image is reproducible and the store
    stays what was fetched, not what was derived from it.
    """
    with _sessions()() as db:
        snapshot = db.get(RawSnapshot, snapshot_id)
        if snapshot is None:
            abort(404)
        storage_key, sha = snapshot.storage_key, snapshot.content_sha256
    # The page comes from immutable bytes, so the reviewer pays for it once.
    etag = f'"{sha}-{page}"'
    if request.if_none_match.contains_raw(etag):
        return Response(status=304, headers={"ETag": etag})
    try:
        content = _store().get(storage_key)
        image = render_page(content, page)
    except (OSError, CorruptSnapshot, NormaliseError, ValueError):
        abort(404)
    return Response(
        image,
        mimetype=PAGE_IMAGE_TYPE,
        headers={"ETag": etag, "Cache-Control": "private, max-age=86400"},
    )


@bp.get("/stavka/<int:item_id>")
def item(item_id: int):
    with _sessions()() as db:
        return _render_item(db, _item_or_404(db, item_id))


def _render_item(db, item, *, error: str | None = None, open_form: str | None = None, typed=None):
    stage = review.stage_of(item)
    payload = item.payload or {}
    call = db.get(Call, item.call_id) if item.call_id else None
    context = {
        "item": item,
        "stage": stage,
        "stage_label": _stage_label(db, item),
        "state_label": STATE_LABELS[item.state],
        "payload": payload,
        "call": call,
        "error": error,
        "open_form": open_form,
        "typed": typed or {},
        "kind_labels": KIND_LABELS,
        "cited_field_labels": CITED_FIELD_LABELS,
        "kinds": list(CriterionKind),
        "fields": list(ProfileField),
        "operators": list(Operator),
        "field_operators": {f.value: sorted(o.value for o in FIELDS[f].operators) for f in FIELDS},
        "manual_outcomes": MANUAL_OUTCOMES,
    }
    if call is not None:
        documents = review.call_documents(db, call)
        texts = {s.id: s for s in documents}
        rows = []
        for criterion in review.criteria_of(db, call):
            snapshot = texts.get(criterion.snapshot_id) or (
                db.get(RawSnapshot, criterion.snapshot_id) if criterion.snapshot_id else None
            )
            rows.append(
                {
                    "c": criterion,
                    "holds": review.citation_holds(criterion, snapshot),
                    "page_image": _page_image_url(snapshot, criterion.quote_start),
                    "context": _in_context(
                        snapshot.normalised_text if snapshot else None,
                        criterion.quote_start,
                        criterion.quote_end,
                    ),
                    "values": ", ".join((criterion.value_json or {}).get("values") or []),
                    "snapshot": snapshot,
                }
            )
        cited = []
        for path, citation in (payload.get("citations") or {}).items():
            if path in CITED_FIELD_LABELS:
                snapshot = texts.get(citation["snapshot_id"])
                cited.append(
                    {
                        "label": CITED_FIELD_LABELS[path],
                        "context": _in_context(
                            snapshot.normalised_text if snapshot else None,
                            citation["char_start"],
                            citation["char_end"],
                        ),
                    }
                )
        source = db.get(SourceFeed, call.source_feed_id)
        context.update(
            rows=rows,
            cited=cited,
            documents=documents,
            source=source,
            days_left=_days_left(call.deadline_at),
            deadline_local=call.deadline_at.astimezone(_tz()) if call.deadline_at else None,
            problems=review.approval_problems(db, item) if stage == review.APPROVE_CALL else [],
            stale_text=review.stale_text_notices(db, call),
            superseded_by=review.superseded_by(db, item),
        )
    elif stage == review.NORMALISE and payload.get("snapshot_id"):
        context["snapshot"] = db.get(RawSnapshot, payload["snapshot_id"])
    status = 422 if error else 200
    return render_template("admin/item.html", **context), status


# -- decisions ----------------------------------------------------------------------------


def _decide(item_id: int, action, *, open_form=None, typed=None):
    """Run one decision in its own transaction; show the operator what stopped it."""
    with _sessions()() as db:
        item = _item_or_404(db, item_id)
        try:
            message = action(db, item)
        except review.ReviewError as exc:
            db.rollback()
            return _render_item(
                db, _item_or_404(db, item_id), error=str(exc), open_form=open_form, typed=typed
            )
        db.commit()
    flash(message)
    return None


@bp.post("/stavka/<int:item_id>/prifati")
def approve(item_id: int):
    note = request.form.get("note", "")

    def act(db, item):
        call = review.approve_call(db, item, note=note, now=_now())
        return f"Повикот „{call.title_mk}“ е објавен."

    return _decide(item_id, act) or redirect(url_for("admin.queue"))


@bp.post("/stavka/<int:item_id>/zatvori")
def reject(item_id: int):
    note = request.form.get("note", "")

    def act(db, item):
        review.close(db, item, note=note, now=_now())
        return f"Ставка {item.id} е затворена. Ништо не е објавено."

    return _decide(item_id, act, open_form="reject") or redirect(url_for("admin.queue"))


@bp.post("/stavka/<int:item_id>/povik")
def edit_call(item_id: int):
    form = request.form

    def act(db, item):
        review.edit_call(
            db,
            item,
            title_mk=form.get("title_mk", ""),
            deadline_date=form.get("deadline_date", ""),
            deadline_time=form.get("deadline_time", ""),
            tz=_tz(),
            now=_now(),
        )
        return "Податоците за повикот се зачувани."

    response = _decide(item_id, act, open_form="call", typed=form.to_dict())
    return response or redirect(url_for("admin.item", item_id=item_id))


@bp.post("/stavka/<int:item_id>/uslov/<uuid:criterion_id>")
def edit_criterion(item_id: int, criterion_id: uuid.UUID):
    form = request.form
    parsed = review.CriterionForm(
        kind=form.get("kind", ""),
        label_mk=form.get("label_mk", ""),
        quote=form.get("quote", ""),
        field=form.get("field", ""),
        operator=form.get("operator", ""),
        values=form.get("values", ""),
        minimum=form.get("minimum", ""),
        maximum=form.get("maximum", ""),
    )

    def act(db, item):
        review.edit_criterion(db, item, criterion_id, parsed, now=_now())
        return "Условот е зачуван, а цитатот повторно е пронајден во документот."

    response = _decide(item_id, act, open_form=f"criterion:{criterion_id}", typed=form.to_dict())
    return response or redirect(
        url_for("admin.item", item_id=item_id, _anchor=f"uslov-{criterion_id}")
    )


@bp.post("/stavka/<int:item_id>/uslov/<uuid:criterion_id>/otstrani")
def remove_criterion(item_id: int, criterion_id: uuid.UUID):
    def act(db, item):
        review.remove_criterion(db, item, criterion_id, now=_now())
        return "Условот е отстранет."

    return _decide(item_id, act) or redirect(url_for("admin.item", item_id=item_id))


# -- manual entry -------------------------------------------------------------------------


@bp.get("/rachen-vnes")
def manual_entry():
    return render_template("admin/manual.html", typed={}, error=None, max_urls=manual.MAX_URLS)


@bp.post("/rachen-vnes")
def manual_entry_submit():
    form = request.form
    try:
        urls = manual.parse_urls(form.get("urls", ""))
        manual.enqueue(
            _settings(), urls, form.get("institution", "").strip(), form.get("note", "").strip()
        )
    except manual.InvalidEntry as exc:
        return _manual_form_error(str(exc), 422)
    except Exception as exc:  # Redis unreachable: say so, keep what was typed
        current_app.logger.warning("manual entry not queued: %s", exc)
        return _manual_form_error(
            "Редот за обработка не е достапен, внесот не е испратен. "
            "Проверете дали работат redis и worker (docker compose ps).",
            503,
        )
    flash(
        f"Внесот е испратен на обработка ({len(urls)} "
        f"{'адреса' if len(urls) == 1 else 'адреси'}). Одговорот ќе се појави во редот, "
        "обично за една до две минути."
    )
    return redirect(url_for("admin.queue"))


def _manual_form_error(message: str, status: int):
    page = render_template(
        "admin/manual.html", typed=request.form.to_dict(), error=message, max_urls=manual.MAX_URLS
    )
    return page, status


# -- reports (P2 s33) ---------------------------------------------------------------------

DECIDED_BY_LABELS = {
    "rule": "Правило над профилот",
    "model": "Проверка според текстот",
    "applicant": "Го потврдува барателот",
}

REPORT_STATE_LABELS = {
    ReviewState.PENDING: "Чека одлука",
    ReviewState.APPROVED: "Прифатен за испраќање",
    ReviewState.EDITED: "Изменет и прифатен за испраќање",
    ReviewState.REJECTED: "Затворен, не се испраќа",
}


def _report_title(item) -> str:
    """What a report item is, in words: how many calls, or why there is no draft."""
    if not reports.is_draft(item):
        return "Одговорот на моделот не ја помина шемата, нема нацрт"
    draft = reports.draft_of(item)
    count = len(draft["calls"])
    return (
        f"Извештај од {mkdate(dt.date.fromisoformat(draft['run_date']))}, "
        f"{count} {'повик' if count == 1 else 'повици'} за проверка"
    )


def _report_or_404(db, item_id: int):
    item = reports.get_item(db, item_id)
    if item is None:
        abort(404)
    return item


def _opened_key(item_id: int) -> str:
    return f"report-opened-{item_id}"


def _passage(snapshots: dict, citation: dict | None) -> dict | None:
    """A citation shown where it stands in the stored text, with the page when OCR'd."""
    if not citation:
        return None
    snapshot = snapshots.get(citation.get("snapshot_id"))
    return {
        "c": citation,
        "context": _in_context(
            snapshot.normalised_text if snapshot else None,
            citation.get("char_start"),
            citation.get("char_end"),
        ),
        "page_image": _page_image_url(snapshot, citation.get("char_start")),
        "ocr": snapshot is not None and snapshot.text_source in (TextSource.OCR, TextSource.MIXED),
    }


@bp.get("/izveshtaj/<int:item_id>")
def report(item_id: int):
    with _sessions()() as db:
        return _render_report(db, _report_or_404(db, item_id))


def _render_report(db, item, *, error=None, open_form=None, typed=None):
    pending = item.state == ReviewState.PENDING
    if pending:
        # The row's acceptance is a time: say it back at the decision (see _decide_report).
        session.setdefault(_opened_key(item.id), _now().isoformat())
    context = {
        "item": item,
        "pending": pending,
        "state_label": REPORT_STATE_LABELS[item.state],
        "error": error,
        "open_form": open_form,
        "typed": typed or {},
        "failures": reports.verification_failures(db, item),
        "decided_by_labels": DECIDED_BY_LABELS,
        "verdicts": Verdict,
    }
    if not reports.is_draft(item):
        context.update(invalid=item.payload or {}, draft=None, problems=[])
        return render_template("admin/report.html", **context), 422 if error else 200

    draft = reports.draft_of(item)
    problems = reports.approval_problems(db, item) if pending else []
    shown, at = [], {}
    for p in problems:
        words, anchor = reports.place(p["where"])
        shown.append({"where": words, "anchor": anchor, "detail": reports.describe(p["detail"])})
        if anchor:
            at.setdefault(anchor, []).append(shown[-1]["detail"])

    ids = {
        cit["snapshot_id"]
        for entry in draft["calls"] + draft["excluded"]
        for c in entry["conditions"]
        for cit in (c.get("citation"), c.get("evidence"))
        if cit and cit.get("snapshot_id") is not None
    }
    snapshots = {s.id: s for s in db.query(RawSnapshot).filter(RawSnapshot.id.in_(ids))}
    passages = {}
    for entry in draft["calls"] + draft["excluded"]:
        for c in entry["conditions"]:
            key = c.get("ref") or c["criterion_id"]
            passages[key] = {
                "citation": _passage(snapshots, c.get("citation")),
                "evidence": _passage(snapshots, c.get("evidence")),
            }
    context.update(
        draft=draft,
        problems=shown,
        problems_at=at,
        passages=passages,
        edits=(item.corrected_payload or {}).get("edits", []),
    )
    return render_template("admin/report.html", **context), 422 if error else 200


def _decide_report(item_id: int, action, *, open_form=None, typed=None):
    with _sessions()() as db:
        item = _report_or_404(db, item_id)
        try:
            message = action(db, item)
        except review.ReviewError as exc:
            db.rollback()
            return _render_report(
                db, _report_or_404(db, item_id), error=str(exc), open_form=open_form, typed=typed
            )
        db.commit()
    flash(message)
    return None


def _minutes_spent(item_id: int) -> str:
    opened = session.pop(_opened_key(item_id), None)
    if opened is None:
        return ""
    minutes = max(1, round((_now() - dt.datetime.fromisoformat(opened)).total_seconds() / 60))
    current_app.logger.info("report item %s decided after %s min", item_id, minutes)
    return f" Прегледот траеше околу {minutes} мин."


def _statement_address(form) -> dict:
    try:
        call = int(form["call"]) if form.get("call") else None
        return {"part": form.get("part", ""), "call": call, "n": int(form.get("n", ""))}
    except ValueError:
        abort(400)


@bp.post("/izveshtaj/<int:item_id>/izjava")
def edit_statement(item_id: int):
    form = request.form
    address = _statement_address(form)
    anchor = reports.place(reports.where(address["part"], address["call"], address["n"]))[1]

    def act(db, item):
        reports.edit_statement(
            db, item, **address, text_mk=form.get("text_mk", ""), cites=form.get("cites", ""),
            now=_now(),
        )  # fmt: skip
        return "Изјавата е зачувана и повторно проверена."

    response = _decide_report(item_id, act, open_form=anchor, typed=form.to_dict())
    return response or redirect(url_for("admin.report", item_id=item_id, _anchor=anchor))


@bp.post("/izveshtaj/<int:item_id>/izjava/otstrani")
def remove_statement(item_id: int):
    address = _statement_address(request.form)

    def act(db, item):
        reports.remove_statement(db, item, **address, now=_now())
        return "Изјавата е отстранета."

    return _decide_report(item_id, act) or redirect(url_for("admin.report", item_id=item_id))


@bp.post("/izveshtaj/<int:item_id>/odobri")
def approve_report(item_id: int):
    note = request.form.get("note", "")

    def act(db, item):
        reports.approve(db, item, note=note, now=_now())
        return f"Извештајот {item.id} е прифатен за испраќање." + _minutes_spent(item.id)

    return _decide_report(item_id, act) or redirect(url_for("admin.queue"))


@bp.post("/izveshtaj/<int:item_id>/zatvori")
def reject_report(item_id: int):
    note = request.form.get("note", "")

    def act(db, item):
        reports.close(db, item, note=note, now=_now())
        return f"Извештајот {item.id} е затворен и нема да се испрати." + _minutes_spent(item.id)

    return _decide_report(item_id, act, open_form="reject") or redirect(url_for("admin.queue"))
