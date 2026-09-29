"""Deciding report review items: the only path by which a paid report is released (P2 s33).

`app/reports/compose.py` writes a draft into `review_queue_item.payload` and never
delivers. A person reads it here, against the stored text of every document it
cites, and decides.

**Approve** calls `compose.blockers()` at the moment of approval and refuses while
it returns anything: the lint over everything the report says in its own voice,
and citation completeness against the stored text (invariant 2). Nothing else
stands between a blocked draft and a customer until s35 renders it, and s35 checks
again.

**Edit** changes the model's prose only: one statement's words and the conditions
it cites. Verdicts, conditions, reasons and quotes are written by code from the
stored run and are not the reviewer's to rewrite here — a wrong verdict is a wrong
criterion or a wrong verification, and the fix belongs there, or the next report
repeats it. An edited statement is validated by the schema the model had to meet
(`ReportStatement`) and by the same checks as the whole draft, so an edit can never
leave a statement uncited, citing another call, or saying "гарантирано". A refused
edit changes nothing.

The edited draft lives in `corrected_payload` (which is what `blockers()` reads),
with an `edits` log of every before and after, for the evaluation loop (s34).
`payload` stays what the model wrote.

**Reject** releases nothing and keeps the reason.

Reviewer identity waits for operator sign-in (docs/decisions.md D11).
"""

import copy
import datetime as dt

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import ReportStatement
from app.models import ReviewQueueItem
from app.models.enums import ReviewKind, ReviewState
from app.reports import compose
from app.review.extraction import ReviewError

SUMMARY, EXPLANATION, NEXT_STEPS = "summary", "explanation", "next_steps"
PARTS = (SUMMARY, EXPLANATION, NEXT_STEPS)


def queue(session: Session, *, recent: int = 10) -> tuple[list[ReviewQueueItem], list]:
    """Pending report items, blocked first, and the latest decisions."""
    pending = session.scalars(
        select(ReviewQueueItem)
        .where(
            ReviewQueueItem.kind == ReviewKind.REPORT,
            ReviewQueueItem.state == ReviewState.PENDING,
        )
        .order_by(ReviewQueueItem.priority, ReviewQueueItem.created_at, ReviewQueueItem.id)
    ).all()
    decided = session.scalars(
        select(ReviewQueueItem)
        .where(
            ReviewQueueItem.kind == ReviewKind.REPORT,
            ReviewQueueItem.state != ReviewState.PENDING,
        )
        .order_by(ReviewQueueItem.resolved_at.desc().nulls_last(), ReviewQueueItem.id.desc())
        .limit(recent)
    ).all()
    return list(pending), list(decided)


def get_item(session: Session, item_id: int) -> ReviewQueueItem | None:
    item = session.get(ReviewQueueItem, item_id)
    return item if item is not None and item.kind == ReviewKind.REPORT else None


def is_draft(item: ReviewQueueItem) -> bool:
    """A composed draft, as opposed to the gateway's record of output it could not
    validate twice (invariant 5), which has nothing to approve."""
    return (item.payload or {}).get("version") == compose.DRAFT_VERSION


def draft_of(item: ReviewQueueItem) -> dict:
    """The draft as it stands: the reviewer's edit, else what was composed."""
    return item.corrected_payload or item.payload


def verification_failures(session: Session, item: ReviewQueueItem) -> list[ReviewQueueItem]:
    """Stage-3 answers from this run that did not pass the gates (app/matching/verify.py).

    Their conditions already stand as needs_verification in the draft; the reviewer
    sees why, because this is the one screen where that run is read by a person.
    """
    if item.match_run_id is None:
        return []
    return list(
        session.scalars(
            select(ReviewQueueItem)
            .where(
                ReviewQueueItem.kind == ReviewKind.VERIFICATION,
                ReviewQueueItem.match_run_id == item.match_run_id,
            )
            .order_by(ReviewQueueItem.id)
        )
    )


def where(part: str, call: int | None, n: int) -> str:
    """A statement's address as `compose` names it in a problem."""
    return f"summary {n}" if part == SUMMARY else f"call {call} {part} {n}"


def approval_problems(session: Session, item: ReviewQueueItem) -> list[dict]:
    """Everything that stops this report being released, as `compose` words it."""
    if item.state != ReviewState.PENDING:
        return [{"check": "state", "where": "item", "detail": "already decided"}]
    if not is_draft(item):
        return [{"check": "version", "where": "draft", "detail": "not a draft"}]
    return compose.blockers(session, item)


def approve(session: Session, item: ReviewQueueItem, *, note: str, now: dt.datetime) -> None:
    """Release the report for rendering (s35). Refused while anything blocks it."""
    problems = approval_problems(session, item)
    if problems:
        raise ReviewError(
            f"Извештајот не може да се одобри: {len(problems)} проблем(и) се уште стојат."
        )
    edited = bool((item.corrected_payload or {}).get("edits"))
    _resolve(item, ReviewState.EDITED if edited else ReviewState.APPROVED, note, now)
    session.flush()


def close(session: Session, item: ReviewQueueItem, *, note: str, now: dt.datetime) -> None:
    if item.state != ReviewState.PENDING:
        raise ReviewError("Ставката е веќе решена.")
    if not note.strip():
        raise ReviewError("Напишете причина: таа станува случај за евалуација.")
    _resolve(item, ReviewState.REJECTED, note, now)
    session.flush()


def edit_statement(
    session: Session,
    item: ReviewQueueItem,
    *,
    part: str,
    call: int | None,
    n: int,
    text_mk: str,
    cites: str,
    now: dt.datetime,
) -> None:
    """Rewrite one statement of the model's prose. Raises ReviewError and changes
    nothing when the result would not pass what the model's own had to."""
    draft = _editable(item)
    statements = _statements(draft, part, call)
    if not 1 <= n <= len(statements):
        raise ReviewError("Таа изјава не постои во нацртот.")
    try:
        statement = ReportStatement(
            text_mk=" ".join(text_mk.split()),
            cites=[ref.strip() for ref in cites.replace(";", ",").split(",") if ref.strip()],
        ).model_dump()
    except ValidationError as exc:
        raise ReviewError(
            "Изјавата не е валидна: " + "; ".join(_schema_message(e) for e in exc.errors())
        ) from exc

    before = statements[n - 1]
    if statement == before:
        return
    statements[n - 1] = statement
    address = where(part, call, n)
    new = [p for p in compose.check(session, draft) if p["where"] == address]
    if new:
        raise ReviewError(
            "Изјавата не е зачувана: " + "; ".join(describe(p["detail"]) for p in new) + "."
        )
    _record(item, draft, address, before, statement, now)
    session.flush()


def remove_statement(
    session: Session, item: ReviewQueueItem, *, part: str, call: int | None, n: int, now
) -> None:
    """Drop a statement the reviewer will not stand behind.

    A call's last explanation cannot go: citation completeness requires one, and a
    report that names a call without saying why is the gap this check exists for.
    """
    draft = _editable(item)
    statements = _statements(draft, part, call)
    if not 1 <= n <= len(statements):
        raise ReviewError("Таа изјава не постои во нацртот.")
    if part in (SUMMARY, EXPLANATION) and len(statements) == 1:
        raise ReviewError(
            "Ова е единствената изјава во делот и не може да се отстрани; измени ја наместо тоа."
        )
    before = statements.pop(n - 1)
    _record(item, draft, where(part, call, n), before, None, now)
    session.flush()


# -- problems, in the reviewer's language ------------------------------------------------

_DETAILS = (
    ("banned phrase: ", "забранет израз: "),
    ("no citation", "нема цитат"),
    ("no source URL or retrieval date", "нема адреса на изворот или датум на преземање"),
    ("a statement that cites nothing", "изјавата не се повикува на ниту еден услов"),
    ("there is no such call", "моделот напиша дел за повик што го нема во извештајот"),
    ("no explanation", "повикот нема објаснување"),
    ("already decided", "ставката е веќе решена"),
    ("not a draft", "ставката не содржи нацрт на извештај"),
)


def describe(detail: str) -> str:
    """compose's problem detail in Macedonian. Unknown wording is shown as it is."""
    for english, mk in _DETAILS:
        if detail.startswith(english):
            return mk + detail[len(english) :]
    if detail.startswith("cites ") and detail.endswith(", not a condition here"):
        ref = detail[len("cites ") : -len(", not a condition here")]
        return f"се повикува на {ref}, што не е услов на овој повик"
    if detail.startswith("the quote is not at "):
        return f"цитатот не стои на знаците {detail[len('the quote is not at ') :]}"
    if detail.startswith("snapshot ") and detail.endswith(" has no stored text"):
        return f"снимката {detail[len('snapshot ') : -len(' has no stored text')]} нема текст"
    if detail.startswith("unknown draft version"):
        return "непозната верзија на нацртот" + detail[len("unknown draft version") :]
    return detail


def place(where_: str) -> tuple[str, str | None]:
    """compose's `where` as (words for the reviewer, the anchor on the page)."""
    words = where_.split()
    if words[0] == "summary":
        return f"Резиме, изјава {words[1]}", f"izjava-summary-{words[1]}"
    if words[0] == "call" and len(words) == 4:
        label = {EXPLANATION: "објаснување", NEXT_STEPS: "следни чекори"}[words[2]]
        return f"Повик {words[1]}, {label} {words[3]}", f"izjava-{words[1]}-{words[2]}-{words[3]}"
    if words[0] == "call":
        return f"Повик {words[1]}", f"povik-{words[1]}"
    if words[0] == "condition":
        ref, rest = words[1], words[2:]
        suffix = {"evidence": ", доказ", "label": ", опис", "reason": ", образложение"}
        anchor = "uslov-" + ref.replace(".", "-")
        return f"Услов {ref}{suffix.get(rest[0], '') if rest else ''}", anchor
    if words[0] == "section":
        return f"Дел за повик {words[-1]}", None
    return where_, None


# -- helpers ------------------------------------------------------------------------------


def _editable(item: ReviewQueueItem) -> dict:
    if item.state != ReviewState.PENDING or not is_draft(item):
        raise ReviewError("Само нацрт што чека одлука може да се менува.")
    draft = copy.deepcopy(draft_of(item))
    draft.pop("problems", None)  # the composer's findings; the screen re-checks
    return draft


def _statements(draft: dict, part: str, call: int | None) -> list[dict]:
    if part == SUMMARY:
        return draft["summary"]
    if part not in PARTS:
        raise ReviewError("Непознат дел од извештајот.")
    for entry in draft["calls"]:
        if entry["number"] == call:
            return entry[part]
    raise ReviewError("Тој повик не е во извештајот.")


def _schema_message(error: dict) -> str:
    field = error["loc"][0] if error["loc"] else ""
    if field == "text_mk":
        return "текстот мора да има меѓу 10 и 700 знаци"
    if field == "cites":
        return "наведете меѓу еден и осум услови, со броеви како 1.2"
    if "not condition numbers" in error["msg"]:
        return "условите се пишуваат со броеви како 1.2, одделени со запирка"
    return error["msg"].removeprefix("Value error, ")


def _record(item, draft: dict, address: str, before, after, now: dt.datetime) -> None:
    draft["edits"] = [
        *draft.get("edits", []),
        {"at": now.isoformat(), "where": address, "before": before, "after": after},
    ]
    item.corrected_payload = draft  # reassigned so SQLAlchemy sees the JSONB change


def _resolve(item: ReviewQueueItem, state: ReviewState, note: str | None, now) -> None:
    item.state = state
    item.reviewer_note = (note or "").strip() or None
    item.resolved_at = now
