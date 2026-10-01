"""Manual entry: a call the operator pastes by URL (docs/sources.md §3, roadmap P1 s16).

Some sources never justify a scraper -- bilateral donors, a one-off ministry call
heard about before it is posted. The operator pastes the call's URLs (the page or
document that states the call first, then its attachments) and the call goes through
exactly the pipeline a crawled one does: polite fetch with robots.txt obeyed,
content-hashed snapshot, normaliser, extraction with quotes located in code, an
unpublished call, and the review queue. Same citation quality, two minutes of the
operator's time.

**Not a scheduled source.** `manual` is `active: false` in config/sources.yaml, so
`flask ingest due` and `flask ingest health` never touch it, and it is not in the
fetcher registry: it takes URLs, and the registry builds fetchers with none.

**Every entry answers in the review queue.** A crawled source that fails is caught
by the health check; a pasted URL that fails would otherwise vanish, because nothing
retries it. So when the fetch fails, when a call could not be processed (provider
down, no key), or when the URLs are already a call or already with a reviewer, the
entry leaves a close-only item saying so (`stage: manual_entry`).

Runs in the RQ worker from the admin form (`enqueue`), or synchronously with
`flask ingest manual`. The worker reloads code only when its container restarts.

The whole page body is normalised (`html_root` is None): unlike a crawled source,
nothing is known about a pasted page's layout, so navigation text can reach the
document. The reviewer reads every quote in context before approving.
"""

import ipaddress
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ingestion import pipeline
from app.ingestion.fetcher import CrawlContext, Fetcher
from app.ingestion.http import PoliteClient, Request
from app.models import ReviewQueueItem
from app.models.enums import ReviewKind

SLUG = "manual"
MAX_URLS = 5
STAGE = "manual_entry"
FETCH_FAILED, PROCESSING_FAILED, ALREADY_KNOWN = "fetch_failed", "processing_failed", "known"

QUEUE = "ingest"
JOB_TIMEOUT_S = 30 * 60  # OCR of a long scanned PDF is minutes; the model call is one


class InvalidEntry(ValueError):
    """The pasted URLs cannot be fetched as given. The message is for the operator."""


def parse_urls(text: str) -> list[str]:
    """One URL per line, the call's own document first. Refuses what must not be fetched."""
    urls = list(dict.fromkeys(line.strip() for line in text.splitlines() if line.strip()))
    if not urls:
        raise InvalidEntry("Внесете барем една адреса.")
    if len(urls) > MAX_URLS:
        raise InvalidEntry(f"Најмногу {MAX_URLS} адреси: повикот и неговите прилози.")
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise InvalidEntry(f"Не е веб-адреса: {url}")
        if _internal(parts.hostname):
            # The fetch runs inside our network. An operator-only form still should not
            # be a way to read the database port or the metadata service.
            raise InvalidEntry(f"Адреса во внатрешна мрежа не се презема: {url}")
    return urls


def _internal(host: str) -> bool:
    if host == "localhost" or host.endswith((".localhost", ".internal", ".local")):
        return True
    if "." not in host:
        return True  # a bare name is a container or intranet host, never a public site
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return not address.is_global


@dataclass
class ManualFetcher(Fetcher):
    urls: list[str]
    institution: str = ""
    note: str = ""
    slug = SLUG

    def crawl(self, ctx: CrawlContext) -> None:
        documents = [ctx.fetch(Request(url)) for url in self.urls]
        ctx.found_call(
            documents[0].response.final_url,
            documents,
            listing={
                "entered_by": "operator",
                "urls": " ".join(self.urls),
                "institution": self.institution,
                "note": self.note,
            },
        )


@dataclass(frozen=True)
class EntryResult:
    outcome: str  # a pipeline outcome, or one of FETCH_FAILED / PROCESSING_FAILED / ALREADY_KNOWN
    review_item_id: int | None
    detail: str = ""


def run_entry(
    urls: list[str],
    *,
    institution: str = "",
    note: str = "",
    settings,
    sessions: sessionmaker[Session],
    store,
    gateway: Callable,
    client: PoliteClient | None = None,
    ocr=None,
) -> EntryResult:
    """Fetch, snapshot and process one pasted call; always leave something in the queue."""
    fetcher = ManualFetcher(urls, institution.strip(), note.strip())
    result = pipeline.run_source(
        fetcher,
        settings=settings,
        sessions=sessions,
        store=store,
        gateway=gateway,
        client=client,
        require_active=False,  # never scheduled; run on demand
        ocr=ocr,
    )
    if not result.run.ok:
        return _answer(sessions, fetcher, FETCH_FAILED, result.run.error or "", call_id=None)
    [processed] = result.processed
    if processed.outcome in (pipeline.CREATED, pipeline.UPDATED, pipeline.REVIEW):
        return EntryResult(processed.outcome, processed.review_item_id, processed.detail)
    if processed.outcome == pipeline.ERROR:
        return _answer(sessions, fetcher, PROCESSING_FAILED, processed.detail, processed.call_id)
    existing = processed.review_item_id
    if existing is None and processed.call_id is not None:
        # Already a call: point at its latest review item, where its decision is.
        with sessions() as session:
            existing = session.scalar(
                select(ReviewQueueItem.id)
                .where(ReviewQueueItem.call_id == processed.call_id)
                .order_by(ReviewQueueItem.id.desc())
                .limit(1)
            )
    known = (
        f"already a call ({processed.call_id})"
        if processed.outcome == pipeline.UNCHANGED
        else f"already with a reviewer (item {processed.review_item_id})"
    )
    return _answer(
        sessions, fetcher, ALREADY_KNOWN, known, processed.call_id, existing_item=existing
    )


def _answer(sessions, fetcher, outcome, detail, call_id, existing_item=None) -> EntryResult:
    reasons = {
        FETCH_FAILED: "manual entry: the URLs could not be fetched",
        PROCESSING_FAILED: "manual entry: fetched, but the call could not be processed",
        ALREADY_KNOWN: "manual entry: nothing new, these documents are already known",
    }
    with sessions() as session:
        item = ReviewQueueItem(
            kind=ReviewKind.EXTRACTION,
            call_id=call_id,
            reason=reasons[outcome],
            payload={
                "stage": STAGE,
                "outcome": outcome,
                "detail": detail[:2000],
                "urls": fetcher.urls,
                "institution": fetcher.institution,
                "note": fetcher.note,
                "existing_item_id": existing_item,
            },
        )
        session.add(item)
        session.commit()
        return EntryResult(outcome, item.id, detail)


# -- the worker ---------------------------------------------------------------------------


def job(urls: list[str], institution: str = "", note: str = "") -> dict:
    """What the RQ worker runs. Builds its own settings and connections, like the CLI."""
    from app.ai.gateway import AnthropicProvider, Gateway
    from app.config import load_settings
    from app.db import session_factory
    from app.ingestion.normalise.pdf import TesseractOcr
    from app.ingestion.snapshots import SnapshotStore

    settings = load_settings()
    sessions = session_factory(settings)
    result = run_entry(
        urls,
        institution=institution,
        note=note,
        settings=settings,
        sessions=sessions,
        store=SnapshotStore(settings.snapshot_dir),
        gateway=lambda: Gateway(sessions, AnthropicProvider()),
        ocr=TesseractOcr(),
    )
    return {"outcome": result.outcome, "review_item_id": result.review_item_id}


def enqueue(settings, urls: list[str], institution: str = "", note: str = "") -> str:
    """Hand an entry to the worker. Raises when Redis cannot be reached."""
    from redis import Redis
    from rq import Queue

    queue = Queue(QUEUE, connection=Redis.from_url(settings.redis_url, socket_timeout=5))
    queued = queue.enqueue(
        job,
        urls,
        institution,
        note,
        job_timeout=JOB_TIMEOUT_S,
        description=f"manual entry {urls[0]}"[:200],
    )
    return queued.id
