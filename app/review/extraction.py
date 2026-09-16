"""Deciding extraction review items: the only path by which a call is published (P1 s15).

The pipeline (app/ingestion/pipeline.py) never publishes. It writes an unpublished
call with unapproved criteria and one review item with `stage: approve_call`, or,
when it cannot vouch for a document, an item that explains why and writes no call.
A human decides here.

**Approve** re-checks, in code and at the moment of approval, everything a customer
could later be shown:

- every criterion still cites its snapshot, and `normalised_text[start:end]` is
  still exactly its stored quote (invariant 2);
- no customer-facing text on the call carries a banned phrase (app/reports/lint.py);
- every hard_structured predicate is still inside the vocabulary
  (app/matching/operators.py).

Only then are the criteria approved, the stage-1 prefilter columns filled from them
(app/matching/hard_filter.py prefilter_columns), and the call published. A problem
blocks approval and is shown; nothing is fixed silently.

**Edit** changes a criterion or the call's title and deadline. An edited criterion is
validated by the same schema extraction uses, and its quote is found verbatim in the
call's documents again, so an edit can never produce an uncited claim. Every edit is
kept in `corrected_payload` with its before and after, for the evaluation loop
(roadmap P2 s34).

**Reject** leaves the call unpublished. The pipeline does not ask the model again
about the same snapshots (pipeline._waiting_item); a changed document at the source
creates a new item.

Reviewer identity waits for operator sign-in (docs/decisions.md D11).
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.schemas import ExtractedCriterion
from app.ingestion.normalise import find_quote
from app.matching.hard_filter import Stored, prefilter_columns
from app.matching.operators import FIELDS, LIST_OPERATORS, Operator, ProfileField
from app.models import (
    Call,
    CallDocument,
    EligibilityCriterion,
    MatchCriterionOutcome,
    RawSnapshot,
    ReviewQueueItem,
)
from app.models.enums import CriterionKind, ReviewKind, ReviewState
from app.reports.lint import find_banned

APPROVE_CALL, NOT_A_CALL, EXTRACT, INVALID_OUTPUT, NORMALISE, MANUAL_ENTRY = (
    "approve_call",
    "not_a_call",
    "extract",
    "invalid_output",
    "normalise",
    "manual_entry",  # app/ingestion/sources/manual.py: an entry that produced no call to approve
)


class ReviewError(ValueError):
    """A decision that cannot be made as asked. The message is for the operator."""


def stage_of(item: ReviewQueueItem) -> str:
    payload = item.payload or {}
    if "errors" in payload:  # the gateway's "failed validation twice"
        return INVALID_OUTPUT
    return payload.get("stage", EXTRACT)


def queue(session: Session, *, recent: int = 20) -> tuple[list[ReviewQueueItem], list]:
    """Pending extraction items, most urgent first, and the latest decisions."""
    pending = session.scalars(
        select(ReviewQueueItem)
        .where(
            ReviewQueueItem.kind == ReviewKind.EXTRACTION,
            ReviewQueueItem.state == ReviewState.PENDING,
        )
        .order_by(ReviewQueueItem.priority, ReviewQueueItem.created_at, ReviewQueueItem.id)
    ).all()
    decided = session.scalars(
        select(ReviewQueueItem)
        .where(
            ReviewQueueItem.kind == ReviewKind.EXTRACTION,
            ReviewQueueItem.state != ReviewState.PENDING,
        )
        .order_by(ReviewQueueItem.resolved_at.desc().nulls_last(), ReviewQueueItem.id.desc())
        .limit(recent)
    ).all()
    return list(pending), list(decided)


def get_item(session: Session, item_id: int) -> ReviewQueueItem | None:
    item = session.get(ReviewQueueItem, item_id)
    return item if item is not None and item.kind == ReviewKind.EXTRACTION else None


def call_documents(session: Session, call: Call) -> list[RawSnapshot]:
    """The call's snapshots, primary first."""
    rows = session.execute(
        select(RawSnapshot, CallDocument.is_primary)
        .join(CallDocument, CallDocument.snapshot_id == RawSnapshot.id)
        .where(CallDocument.call_id == call.id)
        .order_by(CallDocument.is_primary.desc(), RawSnapshot.id)
    ).all()
    return [snapshot for snapshot, _ in rows]


def criteria_of(session: Session, call: Call) -> list[EligibilityCriterion]:
    return list(
        session.scalars(
            select(EligibilityCriterion)
            .where(EligibilityCriterion.call_id == call.id)
            .order_by(
                EligibilityCriterion.is_approved.desc(),
                EligibilityCriterion.snapshot_id,
                EligibilityCriterion.quote_start,
            )
        )
    )


def superseded_by(session: Session, item: ReviewQueueItem) -> int | None:
    """A newer pending approval for the same call: its criteria are the current ones."""
    if item.call_id is None or stage_of(item) != APPROVE_CALL:
        return None
    return session.scalar(
        select(ReviewQueueItem.id)
        .where(
            ReviewQueueItem.call_id == item.call_id,
            ReviewQueueItem.state == ReviewState.PENDING,
            ReviewQueueItem.id > item.id,
            ReviewQueueItem.payload.contains({"stage": APPROVE_CALL}),
        )
        .order_by(ReviewQueueItem.id.desc())
        .limit(1)
    )


def citation_holds(criterion: EligibilityCriterion, snapshot: RawSnapshot | None) -> bool:
    return (
        snapshot is not None
        and snapshot.normalised_text is not None
        and criterion.source_quote is not None
        and criterion.quote_start is not None
        and criterion.quote_end is not None
        and snapshot.normalised_text[criterion.quote_start : criterion.quote_end]
        == criterion.source_quote
    )


def approval_problems(session: Session, item: ReviewQueueItem) -> list[str]:
    """Everything that stops this item being approved. Empty means it can be."""
    if item.state != ReviewState.PENDING:
        return ["Ставката е веќе решена."]
    if stage_of(item) != APPROVE_CALL:
        return ["Оваа ставка нема повик за објавување; може само да се затвори."]
    call = session.get(Call, item.call_id) if item.call_id else None
    if call is None:
        return ["Повикот на оваа ставка повеќе не постои."]
    problems = []
    if (newer := superseded_by(session, item)) is not None:
        problems.append(f"Документот е повторно променет: одлучете на ставка {newer}.")
    if not (call.title_mk or "").strip():
        problems.append("Повикот нема наслов.")
    for label in find_banned(call.title_mk or ""):
        problems.append(f"Насловот содржи забранет израз: {label}.")

    snapshots = {s.id: s for s in call_documents(session, call)}
    for criterion in criteria_of(session, call):
        name = f"„{criterion.label_mk}“"
        snapshot = snapshots.get(criterion.snapshot_id) or (
            session.get(RawSnapshot, criterion.snapshot_id) if criterion.snapshot_id else None
        )
        if not citation_holds(criterion, snapshot):
            problems.append(f"Условот {name} нема цитат што дословно стои во документот.")
        for label in find_banned(criterion.label_mk or ""):
            problems.append(f"Условот {name} содржи забранет израз: {label}.")
        if criterion.kind == CriterionKind.HARD_STRUCTURED:
            try:
                _validate_predicate(criterion.field, criterion.operator, criterion.value_json)
            except ReviewError as exc:
                problems.append(f"Условот {name}: {exc}")
    return problems


def approve_call(
    session: Session, item: ReviewQueueItem, *, note: str | None, now: dt.datetime
) -> Call:
    """Publish the call with its criteria. Raises ReviewError listing what blocks it."""
    problems = approval_problems(session, item)
    if problems:
        raise ReviewError(" ".join(problems))
    call = session.get(Call, item.call_id)
    criteria = criteria_of(session, call)
    for criterion in criteria:
        criterion.is_approved = True

    columns = prefilter_columns(
        [
            Stored.from_row(c.field, c.operator, c.value_json)
            for c in criteria
            if c.kind == CriterionKind.HARD_STRUCTURED
        ]
    )
    call.allowed_entity_types = columns.allowed_entity_types
    call.allowed_nace_prefixes = columns.allowed_nace_prefixes
    call.allowed_regions = columns.allowed_regions
    call.min_company_age_months = columns.min_company_age_months
    call.max_company_age_months = columns.max_company_age_months
    call.is_published = True
    call.updated_at = now

    edited = bool((item.corrected_payload or {}).get("edits"))
    _resolve(item, ReviewState.EDITED if edited else ReviewState.APPROVED, note, now)
    for older in session.scalars(
        select(ReviewQueueItem).where(
            ReviewQueueItem.call_id == call.id,
            ReviewQueueItem.state == ReviewState.PENDING,
            ReviewQueueItem.id < item.id,
            ReviewQueueItem.payload.contains({"stage": APPROVE_CALL}),
        )
    ):
        _resolve(older, ReviewState.REJECTED, f"заменета со ставка {item.id}", now)
    session.flush()
    return call


def close(session: Session, item: ReviewQueueItem, *, note: str, now: dt.datetime) -> None:
    """Reject: nothing is published, and the reason is kept."""
    if item.state != ReviewState.PENDING:
        raise ReviewError("Ставката е веќе решена.")
    if not note.strip():
        raise ReviewError("Напишете причина: таа станува случај за евалуација.")
    _resolve(item, ReviewState.REJECTED, note.strip(), now)
    session.flush()


# -- edits --------------------------------------------------------------------------------


@dataclass
class CriterionForm:
    """What the edit form sends. Strings as typed; parsed here, not in the view."""

    kind: str
    label_mk: str
    quote: str
    field: str = ""
    operator: str = ""
    values: str = ""
    minimum: str = ""
    maximum: str = ""


def edit_criterion(
    session: Session,
    item: ReviewQueueItem,
    criterion_id: uuid.UUID,
    form: CriterionForm,
    *,
    now: dt.datetime,
) -> EligibilityCriterion:
    call, criterion = _editable(session, item, criterion_id)
    try:
        parsed = ExtractedCriterion(
            document=1,
            quote=form.quote.strip(),
            kind=form.kind,
            label_mk=form.label_mk.strip(),
            # A reviewer who makes a condition hard_structured asserts that it applies
            # to every applicant; the form says so next to the choice.
            applies_to_all_applicants=True,
            field=form.field or None,
            operator=form.operator or None,
            values=_split(form.values) if form.operator in LIST_OPERATORS else None,
            minimum=_number(form.minimum),
            maximum=_number(form.maximum),
            confidence=float(criterion.confidence) if criterion.confidence is not None else 1,
        )
    except ValidationError as exc:
        raise ReviewError(
            "Условот не е валиден: "
            + "; ".join(error["msg"].removeprefix("Value error, ") for error in exc.errors())
        ) from exc
    except ValueError as exc:
        raise ReviewError(f"Условот не е валиден: {exc}") from exc

    located = _locate(call_documents(session, call), parsed.quote, prefer=criterion.snapshot_id)
    if located is None:
        raise ReviewError(
            "Цитатот не е пронајден дословно во документите на повикот. "
            "Копирајте го од еден ред на документот."
        )
    snapshot, start, end = located

    before = _criterion_state(criterion)
    criterion.kind = parsed.kind
    criterion.label_mk = parsed.label_mk
    criterion.field = parsed.field
    criterion.operator = parsed.operator
    criterion.value_json = parsed.value_json()
    criterion.snapshot_id = snapshot.id
    criterion.quote_start, criterion.quote_end = start, end
    criterion.source_quote = snapshot.normalised_text[start:end]
    after = _criterion_state(criterion)
    if after != before:
        _record_edit(item, f"criterion:{criterion.id}", before, after, now)
    session.flush()
    return criterion


def remove_criterion(
    session: Session, item: ReviewQueueItem, criterion_id: uuid.UUID, *, now: dt.datetime
) -> None:
    _, criterion = _editable(session, item, criterion_id)
    used = session.scalar(
        select(func.count())
        .select_from(MatchCriterionOutcome)
        .where(MatchCriterionOutcome.criterion_id == criterion.id)
    )
    if used:
        # Deleting would cascade into delivered reports (match_criterion_outcome).
        raise ReviewError(
            f"Условот е дел од {used} резултати на совпаѓање и не може да се избрише."
        )
    _record_edit(item, f"criterion:{criterion.id}", _criterion_state(criterion), None, now)
    session.delete(criterion)
    session.flush()


def edit_call(
    session: Session,
    item: ReviewQueueItem,
    *,
    title_mk: str,
    deadline_date: str,
    deadline_time: str,
    tz,
    now: dt.datetime,
) -> Call:
    if item.state != ReviewState.PENDING or stage_of(item) != APPROVE_CALL or not item.call_id:
        raise ReviewError("Само повик што чека одлука може да се менува.")
    call = session.get(Call, item.call_id)
    title = " ".join(title_mk.split())
    if not title:
        raise ReviewError("Насловот не може да биде празен.")
    try:
        deadline = _deadline(deadline_date, deadline_time, tz)
    except ValueError as exc:
        raise ReviewError("Рокот не е во облик дд.мм.гггг, а времето во чч:мм.") from exc

    before = {"title_mk": call.title_mk, "deadline_at": _iso(call.deadline_at)}
    call.title_mk = title
    call.deadline_at = deadline
    after = {"title_mk": call.title_mk, "deadline_at": _iso(call.deadline_at)}
    if after != before:
        _record_edit(item, "call", before, after, now)
    session.flush()
    return call


# -- helpers ------------------------------------------------------------------------------


def _editable(session, item, criterion_id) -> tuple[Call, EligibilityCriterion]:
    if item.state != ReviewState.PENDING or stage_of(item) != APPROVE_CALL or not item.call_id:
        raise ReviewError("Само услови на повик што чека одлука може да се менуваат.")
    criterion = session.get(EligibilityCriterion, criterion_id)
    if criterion is None or criterion.call_id != item.call_id:
        raise ReviewError("Условот не припаѓа на овој повик.")
    return session.get(Call, item.call_id), criterion


def _validate_predicate(field_name, operator, value_json) -> None:
    try:
        spec = FIELDS[ProfileField(field_name)]
        op = Operator(operator)
    except (KeyError, ValueError) as exc:
        raise ReviewError("полето или операторот не се во речникот на правила.") from exc
    if op not in spec.operators:
        raise ReviewError(f"{field_name} не се споредува со {operator}.")
    stored = Stored.from_row(field_name, operator, value_json)
    if op in LIST_OPERATORS and not stored.value:
        raise ReviewError("недостасуваат вредности.")


def _locate(snapshots: list[RawSnapshot], quote: str, prefer: int | None):
    ordered = sorted(snapshots, key=lambda s: s.id != prefer)
    for snapshot in ordered:
        if not snapshot.normalised_text:
            continue
        spans = find_quote(snapshot.normalised_text, quote, fold=True)
        if spans:
            return snapshot, spans[0].start, spans[0].end
    return None


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


def _number(text: str) -> float | None:
    text = text.strip().replace(" ", "")
    if not text:
        return None
    # 12, 12.5 and 12,5 all mean what they look like; thousands separators are refused.
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    return float(text)


def _deadline(date_text: str, time_text: str, tz) -> dt.datetime | None:
    date_text, time_text = date_text.strip(), time_text.strip()
    if not date_text:
        if time_text:
            raise ValueError("a time without a date")
        return None
    day = dt.datetime.strptime(date_text, "%d.%m.%Y").date()
    # No time given: the end of that day in Skopje, as the pipeline stores it.
    moment = dt.datetime.strptime(time_text, "%H:%M").time() if time_text else dt.time(23, 59, 59)
    return dt.datetime.combine(day, moment, tzinfo=tz)


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _criterion_state(c: EligibilityCriterion) -> dict:
    return {
        "kind": str(c.kind),
        "label_mk": c.label_mk,
        "field": c.field,
        "operator": c.operator,
        "value_json": c.value_json,
        "snapshot_id": c.snapshot_id,
        "quote_start": c.quote_start,
        "quote_end": c.quote_end,
        "source_quote": c.source_quote,
    }


def _record_edit(item: ReviewQueueItem, target: str, before, after, now: dt.datetime) -> None:
    corrected = dict(item.corrected_payload or {})
    corrected["edits"] = [
        *corrected.get("edits", []),
        {"at": now.isoformat(), "target": target, "before": before, "after": after},
    ]
    item.corrected_payload = corrected  # reassigned so SQLAlchemy sees the JSONB change


def _resolve(item: ReviewQueueItem, state: ReviewState, note: str | None, now) -> None:
    item.state = state
    item.reviewer_note = (note or "").strip() or None
    item.resolved_at = now
