"""What happens to a call a crawl found: normalise → extract → an unpublished call.

docs/architecture.md §4. The same for every source; a fetcher only says which
snapshots make up a call (CrawlContext.found_call).

Every found call ends in exactly one of these, on every run:

- **unchanged**: a call already exists for exactly these snapshots. Its
  `last_verified_at` moves forward and nothing is spent.
- **waiting**: a review item already covers these snapshots. A human has it;
  running the model again would only queue the same question twice.
- **created / updated**: an unpublished call with its criteria, each cited
  (snapshot, offsets, verbatim quote, public URL), and one review item asking a
  human to approve it (P1 s15). Nothing here sets `is_published`.
- **review**: the document could not be read, the model's output failed
  validation, a quote was not found verbatim, or the model says the document is
  not a funding call. The review item holds everything; no call is written.
- **error**: something transient (provider outage, no API key). Nothing marks
  the snapshots as handled, so the next run tries again.

A changed document never edits what a customer may already have seen. The call
is unpublished until re-approved, criteria nobody approved are replaced, and
approved criteria are left in place for the reviewer to retire: match outcomes
of delivered reports point at them.

The hard-filter columns on `call` (allowed_entity_types and friends) are left
empty here. They exclude applicants, so they are filled from approved criteria
only, when a human approves (P1 s15).
"""

import datetime as dt
import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.gateway import Gateway, InvalidModelOutput
from app.ai.schemas import CallExtraction, CitedAmount
from app.config import Settings
from app.ingestion.extract import TASK, Document, Extraction, extract_call
from app.ingestion.fetcher import Fetcher, FoundCall, RunResult, run_fetcher
from app.ingestion.http import PoliteClient
from app.ingestion.normalise.pdf import TesseractOcr
from app.ingestion.normalise.snapshot import normalise_snapshot
from app.ingestion.snapshots import SnapshotStore
from app.models import (
    Call,
    CallDocument,
    EligibilityCriterion,
    IngestionRun,
    ModelCall,
    Programme,
    RawSnapshot,
    ReviewQueueItem,
    SourceFeed,
    SourceHealth,
)
from app.models.enums import CallStatus, ReviewKind

UNCHANGED, WAITING, CREATED, UPDATED, REVIEW, ERROR = (
    "unchanged",
    "waiting",
    "created",
    "updated",
    "review",
    "error",
)

# `flask ingest due` runs a source again once its last run is this old. Cron wakes
# it every 4 hours, so a healthy source is checked about once a day and a failed
# run -- fetch or processing -- is retried at the next wake-up (roadmap P1 s11: a
# new call in the database within 24 hours).
RECHECK_AFTER = dt.timedelta(hours=20)

# A previously published call that changed at the source is customer-visible
# until someone looks, so it goes ahead of new calls in the queue.
PRIORITY_WAS_PUBLISHED = 50


@dataclass(frozen=True)
class Processed:
    found: FoundCall
    outcome: str
    call_id: uuid.UUID | None = None
    review_item_id: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class SourceResult:
    run: RunResult
    processed: list[Processed] = field(default_factory=list)
    closed: int = 0

    @property
    def ok(self) -> bool:
        return self.run.ok and not any(p.outcome == ERROR for p in self.processed)


def run_source(
    fetcher: Fetcher,
    *,
    settings: Settings,
    sessions: sessionmaker[Session],
    store: SnapshotStore,
    gateway: Callable[[], Gateway],
    client: PoliteClient | None = None,
    require_active: bool = True,
    ocr: TesseractOcr | None = None,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> SourceResult:
    """Crawl one source, then process every call it found. What cron runs.

    `gateway` is called only when a document actually needs the model, so a run
    in which nothing changed works without provider credentials.
    """
    result = run_fetcher(
        fetcher,
        settings=settings,
        sessions=sessions,
        store=store,
        client=client,
        require_active=require_active,
    )
    pipeline = _Pipeline(
        fetcher, sessions, store, cache(gateway), ocr, ZoneInfo(settings.timezone), now
    )
    processed = [pipeline.process(found) for found in result.found]

    closed = 0
    if result.ok and fetcher.listing_is_complete:
        closed = pipeline.close_unlisted(result.found)

    _record(sessions, result, processed, closed)
    return SourceResult(result, processed, closed)


def due_sources(session: Session, now: dt.datetime) -> list[str]:
    """Active sources, by priority, whose latest run failed, never finished, or is old."""
    due = []
    for source in session.scalars(
        select(SourceFeed)
        .where(SourceFeed.is_active)
        .order_by(SourceFeed.priority, SourceFeed.slug)
    ):
        latest = session.scalars(
            select(IngestionRun)
            .where(IngestionRun.source_feed_id == source.id)
            .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
            .limit(1)
        ).first()
        if latest is None or not latest.ok or latest.started_at < now - RECHECK_AFTER:
            due.append(source.slug)
    return due


class _Pipeline:
    def __init__(self, fetcher, sessions, store, gateway, ocr, tz, now):
        self.fetcher = fetcher
        self.sessions = sessions
        self.store = store
        self.gateway = gateway
        self.ocr = ocr
        self.tz = tz
        self.now = now

    def process(self, found: FoundCall) -> Processed:
        try:
            return self._process(found)
        except Exception as exc:  # transient by assumption: nothing is marked handled
            return Processed(found, ERROR, detail=f"{type(exc).__name__}: {exc}"[:2000])

    def _process(self, found: FoundCall) -> Processed:
        ids = list(found.snapshot_ids)

        # 1. Already done, or already with a human?
        with self.sessions() as session:
            snapshots = _snapshots(session, ids)
            call = _call_for(session, snapshots[0])
            if call is not None and _documents_of(session, call) >= set(ids):
                call.last_verified_at = min(s.last_seen_at for s in snapshots)
                call.status = _status(call.status, call.deadline_at, self.now())
                session.commit()
                return Processed(found, UNCHANGED, call_id=call.id)
            if item := _waiting_item(session, snapshots):
                return Processed(found, WAITING, review_item_id=item.id, call_id=item.call_id)
            call_id = call.id if call else None

            # 2. Normalise. A failure has already created its review item.
            for snapshot in snapshots:
                outcome = normalise_snapshot(
                    session,
                    self.store,
                    snapshot,
                    ocr=self.ocr,
                    html_root=self.fetcher.html_root(snapshot.url),
                    unwrap=self.fetcher.unwrap,
                )
                session.commit()
                if not outcome.ok:
                    return Processed(found, REVIEW, call_id, outcome.review_item_id, outcome.detail)
            documents = [Document.from_snapshot(s) for s in snapshots]

        # 3. Extract, with no transaction held open while the model works.
        try:
            extraction = extract_call(self.gateway(), self.sessions, documents, call_id=call_id)
        except InvalidModelOutput as exc:
            self._tag(exc.review_item_id, ids, found)
            return Processed(found, REVIEW, call_id, exc.review_item_id, "invalid model output")
        if not extraction.ok:
            self._tag(extraction.review_item_id, ids, found)
            detail = f"{len(extraction.failures)} quotes not found verbatim"
            return Processed(found, REVIEW, call_id, extraction.review_item_id, detail)

        # 4. Write.
        with self.sessions() as session:
            if extraction.output.document_kind == "not_a_funding_call":
                item = self._not_a_call(session, found, extraction, call_id)
                session.commit()
                return Processed(found, REVIEW, call_id, item.id, "model says: not a funding call")
            call, created, item = self._write(session, found, extraction, call_id)
            session.commit()
            return Processed(found, CREATED if created else UPDATED, call.id, item.id)

    def close_unlisted(self, found: list[FoundCall]) -> int:
        """Close this source's open calls whose document is no longer listed."""
        with self.sessions() as session:
            listed = select(RawSnapshot.url).where(
                RawSnapshot.id.in_([f.snapshot_ids[0] for f in found])
            )
            calls = session.scalars(
                select(Call)
                .join(RawSnapshot, Call.primary_snapshot_id == RawSnapshot.id)
                .join(SourceFeed, Call.source_feed_id == SourceFeed.id)
                .where(
                    SourceFeed.slug == self.fetcher.slug,
                    Call.status.in_([CallStatus.OPEN, CallStatus.ANNOUNCED]),
                    RawSnapshot.url.not_in(listed),
                )
            ).all()
            for call in calls:
                call.status = CallStatus.CLOSED
                call.updated_at = func.now()
            session.commit()
            return len(calls)

    # -- writing -------------------------------------------------------------------------

    def _write(
        self, session: Session, found: FoundCall, extraction: Extraction, call_id
    ) -> tuple[Call, bool, ReviewQueueItem]:
        out: CallExtraction = extraction.output
        snapshots = _snapshots(session, list(found.snapshot_ids))
        primary = snapshots[0]
        source = session.get(SourceFeed, primary.source_feed_id)
        notes: list[str] = []

        call = session.get(Call, call_id) if call_id else None
        created = call is None
        was_published = bool(call and call.is_published)
        if created:
            call = Call(
                programme_id=_singleton_programme(session, source, primary, out, found).id,
                source_feed_id=source.id,
            )
            session.add(call)

        call.title_mk = out.title_mk.value
        call.reference_code = out.reference_code.value if out.reference_code else None
        call.published_at = out.published_on.value if out.published_on else None
        call.opens_at = out.opens_on.value if out.opens_on else None
        call.deadline_at = self._deadline(out)
        call.total_budget_mkd, call.total_budget_eur = _by_currency(out.total_budget)
        call.grant_min_mkd = _mkd_only(out.grant_min, "grant_min", notes)
        call.grant_max_mkd = _mkd_only(out.grant_max, "grant_max", notes)
        call.canonical_url = found.public_url
        call.primary_snapshot_id = primary.id
        call.last_verified_at = min(s.last_seen_at for s in snapshots)
        call.extraction_confidence = min((c.confidence for c in out.criteria), default=None)
        call.is_published = False
        kind = CallStatus.ANNOUNCED if out.document_kind == "advance_notice" else CallStatus.OPEN
        call.status = _status(kind, call.deadline_at, self.now())
        call.updated_at = func.now()
        session.flush()

        linked = {doc.snapshot_id: doc for doc in _call_documents(session, call)}
        for index, snapshot in enumerate(snapshots):
            if snapshot.id not in linked:
                linked[snapshot.id] = CallDocument(
                    call_id=call.id,
                    snapshot_id=snapshot.id,
                    role="call_text" if index == 0 else "attachment",
                )
                session.add(linked[snapshot.id])
        for snapshot_id, doc in linked.items():
            doc.is_primary = snapshot_id == primary.id

        kept = session.scalar(
            select(func.count())
            .select_from(EligibilityCriterion)
            .where(EligibilityCriterion.call_id == call.id, EligibilityCriterion.is_approved)
        )
        session.execute(
            delete(EligibilityCriterion).where(
                EligibilityCriterion.call_id == call.id, EligibilityCriterion.is_approved.is_(False)
            )
        )
        prompt_version = session.scalar(
            select(ModelCall.prompt_version_id).where(ModelCall.id == extraction.model_call_id)
        )
        for index, criterion in enumerate(out.criteria):
            citation = extraction.citations[f"criteria.{index}"]
            if citation.occurrences > 1:
                notes.append(
                    f"criteria.{index}: the quote appears {citation.occurrences} times; "
                    "the first is cited"
                )
            session.add(
                EligibilityCriterion(
                    call_id=call.id,
                    kind=criterion.kind,
                    label_mk=criterion.label_mk,
                    field=criterion.field,
                    operator=criterion.operator,
                    value_json=criterion.value_json(),
                    source_quote=citation.source_quote,
                    snapshot_id=citation.snapshot_id,
                    quote_start=citation.char_start,
                    quote_end=citation.char_end,
                    source_url=found.public_url,
                    confidence=criterion.confidence,
                    prompt_version=prompt_version,
                    is_approved=False,
                )
            )

        if created:
            reason = f"new call from {source.slug}: approve before publishing"
        else:
            reason = f"call document changed at {source.slug}: re-approve"
            if was_published:
                reason += " (was published; unpublished until then)"
            if kept:
                reason += f"; {kept} previously approved criteria kept for you to retire"
        item = ReviewQueueItem(
            kind=ReviewKind.EXTRACTION,
            priority=PRIORITY_WAS_PUBLISHED if was_published else 100,
            call_id=call.id,
            reason=reason,
            payload=_payload(found, extraction, stage="approve_call", notes=notes),
        )
        session.add(item)
        session.flush()
        return call, created, item

    def _not_a_call(self, session, found, extraction, call_id) -> ReviewQueueItem:
        reason = f"{TASK}: the model says this is not a funding call; no call was written"
        call = session.get(Call, call_id) if call_id else None
        if call is not None and call.is_published:
            call.is_published = False
            reason += "; the existing call was unpublished"
        item = ReviewQueueItem(
            kind=ReviewKind.EXTRACTION,
            call_id=call_id,
            reason=reason,
            payload=_payload(found, extraction, stage="not_a_call"),
        )
        session.add(item)
        session.flush()
        return item

    def _tag(self, review_item_id: int, ids: list[int], found: FoundCall) -> None:
        """Mark a review item as covering these snapshots, so the next run waits for it."""
        with self.sessions() as session:
            item = session.get(ReviewQueueItem, review_item_id)
            item.payload = {
                **item.payload,
                "stage": item.payload.get("stage", "extract"),
                "snapshot_ids": ids,
                "public_url": found.public_url,
                "listing": found.listing,
            }
            session.commit()

    def _deadline(self, out: CallExtraction) -> dt.datetime | None:
        if out.deadline is None:
            return None
        if out.deadline.time:
            hour, minute = (int(part) for part in out.deadline.time.split(":"))
            local = dt.time(hour, minute)
        else:
            # A date without a time is taken as the end of that day in Skopje, so
            # a call is never shown as closed on its own last day. The page shows
            # the date only.
            local = dt.time(23, 59, 59)
        return dt.datetime.combine(out.deadline.value, local, tzinfo=self.tz)


# -- queries and small helpers -----------------------------------------------------------


def _snapshots(session: Session, ids: list[int]) -> list[RawSnapshot]:
    rows = {s.id: s for s in session.scalars(select(RawSnapshot).where(RawSnapshot.id.in_(ids)))}
    return [rows[i] for i in ids]


def _call_for(session: Session, primary: RawSnapshot) -> Call | None:
    """The call whose primary document is this URL, whichever version of it."""
    return session.scalars(
        select(Call)
        .join(RawSnapshot, Call.primary_snapshot_id == RawSnapshot.id)
        .where(Call.source_feed_id == primary.source_feed_id, RawSnapshot.url == primary.url)
        .order_by(Call.created_at)
        .limit(1)
    ).first()


def _call_documents(session: Session, call: Call) -> list[CallDocument]:
    return list(session.scalars(select(CallDocument).where(CallDocument.call_id == call.id)))


def _documents_of(session: Session, call: Call) -> set[int]:
    if call.primary_snapshot_id is None:
        return set()
    linked = {doc.snapshot_id for doc in _call_documents(session, call)}
    return linked if call.primary_snapshot_id in linked else set()


def _waiting_item(session: Session, snapshots: list[RawSnapshot]) -> ReviewQueueItem | None:
    """A review item, in any state, that already covers these snapshots.

    Resolved items count too: a reviewer who rejected an extraction has decided,
    and asking the model again every night would put the same question back.
    """
    ids = [s.id for s in snapshots]
    item = session.scalars(
        select(ReviewQueueItem)
        .where(ReviewQueueItem.payload.contains({"snapshot_ids": ids}))
        .order_by(ReviewQueueItem.id.desc())
        .limit(1)
    ).first()
    if item is not None:
        return item
    for snapshot in snapshots:
        if snapshot.normalised_text is not None:
            continue  # read, perhaps with doubt; that item does not block extraction
        item = session.scalars(
            select(ReviewQueueItem)
            .where(
                ReviewQueueItem.payload.contains({"stage": "normalise", "snapshot_id": snapshot.id})
            )
            .limit(1)
        ).first()
        if item is not None:
            return item
    return None


def _singleton_programme(
    session: Session,
    source: SourceFeed,
    primary: RawSnapshot,
    out: CallExtraction,
    found: FoundCall,
) -> Programme:
    """Every new call starts in a programme of its own (docs/data-model.md).

    Joining recurring calls into one durable programme is a human decision; a
    wrong merge would carry one call's history onto another.

    The institution is the source's, unless the listing names one: a manually
    entered call (sources/manual.py) comes from whoever published it, not from
    "manual entry".
    """
    slug = f"{source.slug}-{hashlib.sha256(primary.url.encode()).hexdigest()[:12]}"
    programme = session.scalars(select(Programme).where(Programme.slug == slug)).first()
    if programme is None:
        programme = Programme(
            source_feed_id=source.id,
            slug=slug,
            name_mk=out.title_mk.value,
            institution=found.listing.get("institution") or source.institution,
            is_singleton=True,
        )
        session.add(programme)
        session.flush()
    return programme


def _status(current: CallStatus, deadline_at: dt.datetime | None, now: dt.datetime) -> CallStatus:
    if current in (CallStatus.CANCELLED, CallStatus.ANNOUNCED):
        return current
    if deadline_at is not None and deadline_at <= now:
        return CallStatus.CLOSED
    return CallStatus.OPEN


def _by_currency(amount: CitedAmount | None) -> tuple[float | None, float | None]:
    if amount is None:
        return None, None
    return (amount.amount, None) if amount.currency == "MKD" else (None, amount.amount)


def _mkd_only(amount: CitedAmount | None, name: str, notes: list[str]) -> float | None:
    if amount is None:
        return None
    if amount.currency != "MKD":
        # No conversion: an exchange rate would be a number nobody can cite.
        notes.append(f"{name} is {amount.amount} {amount.currency}; the column holds MKD only")
        return None
    return amount.amount


def _payload(found: FoundCall, extraction: Extraction, *, stage: str, notes=()) -> dict:
    return {
        "stage": stage,
        "snapshot_ids": list(found.snapshot_ids),
        "model_call_id": extraction.model_call_id,
        "public_url": found.public_url,
        "listing": found.listing,
        "notes": list(notes),
        "citations": {
            path: {
                "snapshot_id": c.snapshot_id,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "source_quote": c.source_quote,
                "occurrences": c.occurrences,
            }
            for path, c in extraction.citations.items()
        },
        "extraction": extraction.output.model_dump(mode="json"),
    }


def _record(
    sessions: sessionmaker[Session], result: RunResult, processed: list[Processed], closed: int
) -> None:
    counts = {outcome: 0 for outcome in (CREATED, UPDATED, REVIEW, ERROR)}
    for p in processed:
        if p.outcome in counts:
            counts[p.outcome] += 1
    with sessions() as session:
        run = session.get(IngestionRun, result.run_id)
        run.items_created = counts[CREATED]
        run.items_updated = counts[UPDATED] + closed
        # Every created or updated call also waits for approval.
        run.queued_for_review = counts[REVIEW] + counts[CREATED] + counts[UPDATED]
        if counts[ERROR]:
            # The source answered (its health stays good); what failed was ours.
            run.ok = False
            errors = [p.detail for p in processed if p.outcome == ERROR]
            run.error = "\n".join(
                filter(None, [run.error, f"processing failed for {counts[ERROR]} calls:", *errors])
            )[:2000]
        if counts[CREATED]:
            health = session.get(SourceHealth, run.source_feed_id)
            health.last_new_item_at = func.now()
        session.commit()
