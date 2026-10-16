"""Deciding document-package review items: the only path by which a package is sent (P5 s75).

`app/documents/packages.py` makes a paid order's package and queues it; nothing is delivered
until a person has opened its documents here and approved. What the reviewer checks, and the
page says: the forms are the institution's current ones (each shows its source and the date it
was taken), the company's details are right, nothing of the applicant's was filled.

**Approve** checks again that every stored file is still there and intact (the store checks
each against its hash) and still carries its draft label. **Close** keeps the reason, sends
nothing, and leaves the order in progress for the operator to settle with the buyer.
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents import label
from app.ingestion.snapshots import CorruptSnapshot
from app.models import ReviewQueueItem
from app.models.enums import ReviewKind, ReviewState
from app.review.extraction import ReviewError


def queue(session: Session, *, recent: int = 10) -> tuple[list[ReviewQueueItem], list]:
    """Pending package items, oldest first, and the latest decisions."""
    kind = ReviewQueueItem.kind == ReviewKind.DOCUMENT_PACKAGE
    pending = session.scalars(
        select(ReviewQueueItem)
        .where(kind, ReviewQueueItem.state == ReviewState.PENDING)
        .order_by(ReviewQueueItem.created_at, ReviewQueueItem.id)
    ).all()
    decided = session.scalars(
        select(ReviewQueueItem)
        .where(kind, ReviewQueueItem.state != ReviewState.PENDING)
        .order_by(ReviewQueueItem.resolved_at.desc().nulls_last(), ReviewQueueItem.id.desc())
        .limit(recent)
    ).all()
    return list(pending), list(decided)


def get_item(session: Session, item_id: int) -> ReviewQueueItem | None:
    item = session.get(ReviewQueueItem, item_id)
    return item if item is not None and item.kind == ReviewKind.DOCUMENT_PACKAGE else None


def problems(store, item: ReviewQueueItem) -> list[str]:
    """Why the package cannot be sent as it stands, one line each; empty when it can."""
    found = []
    keys = [(d["title_mk"], d["key"]) for d in item.payload.get("documents", [])]
    for title, key in keys:
        try:
            content = store.get(key)
        except (FileNotFoundError, CorruptSnapshot):
            found.append(f"«{title}»: датотеката ја нема или е оштетена")
            continue
        if not label.is_labelled(content):
            found.append(f"«{title}»: нема ознака за нацрт")
    try:
        store.get(item.payload.get("checklist_key", ""))
    except (FileNotFoundError, CorruptSnapshot, ValueError):
        found.append("Листата „Што уште треба да подготвите“ ја нема")
    return found


def approve(session: Session, store, item: ReviewQueueItem, *, note: str, now: dt.datetime) -> None:
    if item.state != ReviewState.PENDING:
        raise ReviewError("Ставката е веќе решена.")
    found = problems(store, item)
    if found:
        raise ReviewError("Пакетот не може да се прифати: " + "; ".join(found))
    _resolve(item, ReviewState.APPROVED, note, now)
    session.flush()


def close(session: Session, item: ReviewQueueItem, *, note: str, now: dt.datetime) -> None:
    if item.state != ReviewState.PENDING:
        raise ReviewError("Ставката е веќе решена.")
    if not note.strip():
        raise ReviewError("Напишете причина: што не е во ред со пакетот.")
    _resolve(item, ReviewState.REJECTED, note, now)
    session.flush()


def _resolve(item: ReviewQueueItem, state: ReviewState, note: str | None, now) -> None:
    item.state = state
    item.reviewer_note = (note or "").strip() or None
    item.resolved_at = now
