"""Normalising stored snapshots: the database side of the normaliser."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.normalise import NORMALISER_VERSION, NormaliseError, normalise
from app.ingestion.normalise.pdf import TesseractOcr
from app.ingestion.snapshots import SnapshotStore
from app.models import RawSnapshot, ReviewQueueItem
from app.models.enums import ReviewKind


@dataclass(frozen=True)
class Outcome:
    snapshot_id: int
    ok: bool
    review_item_id: int | None = None
    detail: str = ""


def normalise_snapshot(
    session: Session,
    store: SnapshotStore,
    snapshot: RawSnapshot,
    *,
    ocr: TesseractOcr | None = None,
    html_root: str | None = None,
) -> Outcome:
    """Fill normalised_text once. Anything uncertain goes to review; nothing is dropped.

    A document that cannot be read at all leaves normalised_text empty and creates
    a review item. A document that was read but with doubt (low OCR confidence)
    keeps its text -- a reviewer needs something to look at -- and also creates one.
    """
    if snapshot.normalised_text is not None:
        # Never rewritten: evidence rows may already cite these offsets.
        return Outcome(snapshot.id, ok=True, detail="already normalised")

    try:
        result = normalise(
            store.get(snapshot.storage_key), snapshot.content_type, ocr=ocr, html_root=html_root
        )
    except (NormaliseError, OSError) as exc:
        item = _review(session, snapshot, [f"{type(exc).__name__}: {exc}"])
        return Outcome(snapshot.id, ok=False, review_item_id=item.id, detail=str(exc))

    snapshot.normalised_text = result.text
    snapshot.normaliser_version = (
        f"{NORMALISER_VERSION}+{result.ocr_engine}" if result.ocr_engine else NORMALISER_VERSION
    )
    snapshot.text_source = result.text_source
    snapshot.ocr_mean_confidence = result.ocr_mean_confidence
    session.flush()

    if result.review_reasons:
        item = _review(session, snapshot, list(result.review_reasons))
        return Outcome(
            snapshot.id, ok=True, review_item_id=item.id, detail="; ".join(result.review_reasons)
        )
    return Outcome(
        snapshot.id, ok=True, detail=f"{len(result.text)} characters, {result.text_source}"
    )


def pending_snapshots(session: Session, limit: int = 100) -> list[RawSnapshot]:
    """Snapshots never normalised and not already waiting in review for it."""
    snapshot_id = ReviewQueueItem.payload["snapshot_id"].as_integer()
    in_review = select(snapshot_id).where(
        ReviewQueueItem.payload["stage"].as_string() == "normalise",
        # NOT IN over a set containing NULL matches nothing, which would silently
        # stop all normalisation.
        snapshot_id.is_not(None),
    )
    return list(
        session.scalars(
            select(RawSnapshot)
            .where(RawSnapshot.normalised_text.is_(None), RawSnapshot.id.not_in(in_review))
            .order_by(RawSnapshot.id)
            .limit(limit)
        )
    )


def _review(session: Session, snapshot: RawSnapshot, reasons: list[str]) -> ReviewQueueItem:
    item = ReviewQueueItem(
        kind=ReviewKind.EXTRACTION,
        reason=f"normalising snapshot {snapshot.id} needs a human",
        payload={
            "stage": "normalise",
            "snapshot_id": snapshot.id,
            "url": snapshot.url,
            "reasons": reasons,
            "normaliser_version": NORMALISER_VERSION,
        },
    )
    session.add(item)
    session.flush()
    return item
