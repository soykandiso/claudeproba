"""Operator commands. Cron runs these as `docker compose exec web flask ...`."""

import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from flask import Flask, current_app
from sqlalchemy import select

from app.ai.gateway import AnthropicProvider, Gateway, InvalidModelOutput
from app.db import session_factory
from app.heartbeat import ping
from app.ingestion.extract import Document, extract_call
from app.ingestion.fetcher import CrawlContext, Fetcher, run_fetcher
from app.ingestion.health import run_health_check
from app.ingestion.normalise import NORMALISER_VERSION, missing_repairs
from app.ingestion.normalise.pdf import TesseractOcr
from app.ingestion.normalise.snapshot import normalise_snapshot, pending_snapshots
from app.ingestion.pipeline import ERROR, UNCHANGED, due_sources, run_source
from app.ingestion.snapshots import SnapshotStore, without_aspnet_state
from app.ingestion.source_config import load_sources, sync_sources
from app.ingestion.sources import fetchers, manual
from app.models import Call, EligibilityCriterion, RawSnapshot, ReviewQueueItem, SourceFeed
from app.reports import render
from app.retrieval.embedder import LocalEmbedder
from app.retrieval.index import index_pending
from app.review import cases


def register_cli(app: Flask) -> None:
    app.cli.add_command(ingest)
    app.cli.add_command(review)


@click.group(help="Fetch sources and store snapshots.")
def ingest():
    pass


def _settings():
    return current_app.extensions["settings"]


@ingest.command("sync-sources", help="Write config/sources.yaml into source_feed.")
def sync_sources_command():
    sessions = session_factory(_settings())
    with sessions() as session:
        changes = sync_sources(session, load_sources())
        session.commit()
    click.echo("\n".join(changes) or "source_feed already matches config/sources.yaml")


@ingest.command(
    "run",
    help="Crawl one source, then normalise, extract and write every call it found "
    "(unpublished, queued for review).",
)
@click.argument("slug")
@click.option(
    "--allow-inactive", is_flag=True, help="Run a source still `active: false`, to check it."
)
def run_command(slug, allow_inactive):
    available = fetchers()
    if slug not in available:
        raise click.ClickException(
            f"no fetcher for {slug!r}; have: {', '.join(available) or 'none'}"
        )
    ok = _run_source(available[slug](), allow_inactive=allow_inactive)
    if not (_index() and ok):
        sys.exit(1)


@ingest.command(
    "due", help="Run every active source whose last run failed or is more than 20 hours old."
)
def due_command():
    settings = _settings()
    available = fetchers()
    with session_factory(settings)() as session:
        slugs = due_sources(session, dt.datetime.now(dt.UTC))
    failed = False
    summary = []
    for slug in slugs:
        if slug not in available:
            # Active in config but no code: a deploy mistake, and loud on purpose.
            click.echo(f"{slug}: active in config/sources.yaml but has no fetcher", err=True)
            summary.append(f"{slug}: NO FETCHER")
            failed = True
            continue
        click.echo(f"== {slug}")
        ok = _run_source(available[slug]())
        summary.append(f"{slug}: {'ok' if ok else 'FAILED'}")
        failed |= not ok
    if not slugs:
        click.echo("nothing due")
        summary.append("nothing due")
    # Also when nothing was due: an earlier run may have stopped before embedding.
    indexed = _index()
    summary.append(f"index: {'ok' if indexed else 'FAILED'}")
    failed |= not indexed
    # Always a success ping: it says cron and this command are alive. Whether a
    # source is in trouble is `flask ingest health`'s judgement, with the patience
    # a flaky ministry server needs; a failure here would email every 4 hours.
    click.echo(ping(settings.heartbeat_ingest_url, ok=True, body="\n".join(summary)))
    if failed:
        sys.exit(1)


@ingest.command(
    "manual",
    help="Enter a call by URL: the call's own page or document first, then its attachments. "
    "Runs the whole pipeline now; the answer lands in the review queue.",
)
@click.argument("urls", nargs=-1, required=True)
@click.option("--institution", default="", help="Who published the call, as it should be shown.")
@click.option("--note", default="", help="Where you heard about it, for the reviewer.")
def manual_command(urls, institution, note):
    settings = _settings()
    try:
        parsed = manual.parse_urls("\n".join(urls))
    except manual.InvalidEntry as exc:
        raise click.ClickException(str(exc)) from exc
    sessions = session_factory(settings)
    result = manual.run_entry(
        parsed,
        institution=institution,
        note=note,
        settings=settings,
        sessions=sessions,
        store=SnapshotStore(settings.snapshot_dir),
        gateway=lambda: Gateway(sessions, AnthropicProvider()),
        ocr=TesseractOcr(),
    )
    detail = f": {result.detail}" if result.detail else ""
    click.echo(f"{result.outcome}, review item {result.review_item_id}{detail}")
    # Chunks and embeddings for the new snapshots, as `due` does after a crawl.
    if not _index():
        sys.exit(1)


@ingest.command(
    "health",
    help="Judge every active source (failing, not running, quiet) and report to the "
    "health check, which emails. Exits 1 when any source needs attention.",
)
@click.option(
    "--drill",
    is_flag=True,
    help="Send a test alert through the health check, to confirm it reaches you.",
)
def health_command(drill):
    settings = _settings()
    url = settings.heartbeat_health_url
    if not url and settings.is_production:
        raise click.ClickException(
            "GRANTS_HEARTBEAT_HEALTH_URL is not set: source alerts cannot leave the box"
        )
    tz = ZoneInfo(settings.timezone)
    now = dt.datetime.now(dt.UTC)
    if drill:
        body = (
            f"DRILL {now.astimezone(tz):%d.%m.%Y %H:%M}: a test alert from `flask ingest "
            "health --drill`. No source is broken. Run `flask ingest health` to clear it."
        )
        click.echo(body)
        line = ping(url, ok=False, body=body)
        click.echo(line)
        if not line.startswith("heartbeat sent"):
            sys.exit(1)  # a drill that did not leave the box proves nothing
        return
    result = run_health_check(session_factory(settings), url=url, now=now, tz=tz)
    click.echo(result.text)
    for line in result.heartbeat:
        click.echo(line)
    if result.alerting:
        sys.exit(1)


@ingest.command(
    "index",
    help="Chunk normalised snapshots that have no chunks, and embed chunks that have no "
    "vector from the current model.",
)
def index_command():
    if not _index():
        sys.exit(1)


@ingest.command(
    "fetch-model",
    help="Download the embedding model into GRANTS_MODEL_DIR (~2.2 GB). Once per machine, "
    "and again after changing it in config/models.yaml.",
)
def fetch_model_command():
    embedder = LocalEmbedder(_settings().model_dir)
    embedder.download()
    embedder.passages(["проверка"])  # loads the way indexing will, offline
    click.echo(f"{embedder.name} ready in {_settings().model_dir}")


@ingest.command(
    "snapshot", help="Fetch one URL for a source and store it. For checks and debugging."
)
@click.argument("slug")
@click.argument("url")
@click.option("--ignore-aspnet-state", is_flag=True, help="Ignore __VIEWSTATE when comparing.")
def snapshot_command(slug, url, ignore_aspnet_state):
    class OneUrl(Fetcher):
        def significant(self, content: bytes) -> bytes:
            return without_aspnet_state(content) if ignore_aspnet_state else content

        def crawl(self, ctx: CrawlContext) -> None:
            fetched = ctx.fetch(url)
            snap = fetched.recorded.snapshot
            state = "CHANGED, stored" if fetched.changed else "unchanged, nothing stored"
            click.echo(f"{state}: snapshot {snap.id}, {snap.byte_length} bytes, {snap.storage_key}")

    OneUrl.slug = slug
    sessions = session_factory(_settings())
    with sessions() as session:
        if session.scalars(select(SourceFeed).where(SourceFeed.slug == slug)).first() is None:
            raise click.ClickException(f"no source_feed {slug!r}; run `flask ingest sync-sources`")
    _run(OneUrl(), allow_inactive=True)


@ingest.command("normalise", help="Turn stored snapshots into text for citations.")
@click.option("--snapshot-id", type=int, help="One snapshot instead of all pending ones.")
@click.option("--limit", default=100, show_default=True)
def normalise_command(snapshot_id, limit):
    settings = _settings()
    store = SnapshotStore(settings.snapshot_dir)
    ocr = TesseractOcr()
    with session_factory(settings)() as session:
        if snapshot_id is not None:
            snapshot = session.get(RawSnapshot, snapshot_id)
            if snapshot is None:
                raise click.ClickException(f"no snapshot {snapshot_id}")
            snapshots = [snapshot]
        else:
            snapshots = pending_snapshots(session, limit)
        registered = fetchers()
        for snapshot in snapshots:
            fetcher_cls = registered.get(session.get(SourceFeed, snapshot.source_feed_id).slug)
            fetcher = fetcher_cls() if fetcher_cls else None
            outcome = normalise_snapshot(
                session,
                store,
                snapshot,
                ocr=ocr,
                html_root=fetcher.html_root(snapshot.url) if fetcher else None,
                unwrap=fetcher.unwrap if fetcher else None,
            )
            session.commit()  # one document at a time: OCR is slow, keep what is done
            flag = f" -> review item {outcome.review_item_id}" if outcome.review_item_id else ""
            click.echo(f"snapshot {outcome.snapshot_id}: {outcome.detail}{flag}")
    if not snapshots:
        click.echo("nothing to normalise")


@ingest.command(
    "stale-text",
    help="Snapshots whose text predates a normaliser repair, and what still cites them.",
)
def stale_text_command():
    """What is still being read out of text an older normaliser wrote.

    Normalised text is written once and an unchanged document is never fetched
    again, so a snapshot read before 21.09.2026 keeps the missing percent signs and
    the garbled Albanian for ever (`docs/sources.md` §6.10, §6.11). The citation
    check cannot see it — the quote is verbatim against text that is itself wrong —
    so this is the inventory of what has to be deleted and re-fetched before launch.

    Nothing is changed here. Clearing a snapshot's text moves every offset that
    cites it, so it is its own decision and its own session.
    """
    settings = _settings()
    published_ids = []
    with session_factory(settings)() as session:
        rows = session.scalars(
            select(RawSnapshot)
            .where(RawSnapshot.normalised_text.is_not(None))
            .order_by(RawSnapshot.id)
        )
        affected = [
            (snapshot, missing)
            for snapshot in rows
            if (missing := missing_repairs(snapshot.normaliser_version, snapshot.text_source))
        ]
        if not affected:
            click.echo(f"every stored text is current ({NORMALISER_VERSION})")
            return
        for snapshot, missing in affected:
            criteria = list(
                session.scalars(
                    select(EligibilityCriterion).where(
                        EligibilityCriterion.snapshot_id == snapshot.id
                    )
                )
            )
            approved = [c for c in criteria if c.is_approved]
            calls = {c.call_id for c in criteria}
            published = session.scalars(
                select(Call.id).where(Call.id.in_(calls), Call.is_published.is_(True))
            ).all()
            published_ids.extend(published)
            click.echo(
                f"snapshot {snapshot.id}: {snapshot.normaliser_version} "
                f"({snapshot.text_source}), missing {', '.join(missing)}"
            )
            click.echo(f"    {snapshot.url}")
            click.echo(
                f"    {len(criteria)} criteria ({len(approved)} approved) on "
                f"{len(calls)} call(s), {len(published)} of them published"
            )
    click.echo(
        f"\n{len(affected)} snapshot(s) predate {NORMALISER_VERSION}."
        " Delete and re-fetch before launch; nothing re-normalises in place.",
        err=True,
    )
    if published_ids:
        # A published call built on text known to be wrong is the case this command
        # exists to make impossible to forget.
        click.echo(f"{len(set(published_ids))} published call(s) cite one", err=True)
        sys.exit(1)


@ingest.command(
    "extract",
    help="Run extraction over normalised snapshots of one call and print what came back. "
    "Stores the model call and any review item; writes no call or criteria.",
)
@click.option("--snapshot-id", "snapshot_ids", type=int, multiple=True, required=True)
def extract_command(snapshot_ids):
    settings = _settings()
    sessions = session_factory(settings)
    with sessions() as session:
        snapshots = [session.get(RawSnapshot, sid) for sid in snapshot_ids]
        pairs = zip(snapshot_ids, snapshots, strict=True)
        if missing := [sid for sid, snap in pairs if snap is None]:
            raise click.ClickException(f"no snapshot {missing}")
        try:
            documents = [Document.from_snapshot(snap) for snap in snapshots]
        except ValueError as exc:
            raise click.ClickException(f"{exc}; run `flask ingest normalise` first") from exc
    try:
        provider = AnthropicProvider()
    except Exception as exc:  # the SDK refuses to construct without credentials
        raise click.ClickException(f"no model provider: {exc}") from exc

    try:
        extraction = extract_call(Gateway(sessions, provider), sessions, documents)
    except InvalidModelOutput as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(extraction.output.model_dump_json(indent=2))
    cache = " (cache hit)" if extraction.cache_hit else ""
    click.echo(f"model_call {extraction.model_call_id}{cache}", err=True)
    for failure in extraction.failures:
        click.echo(f"NOT FOUND {failure.path}: {failure.quote!r}", err=True)
    if extraction.review_item_id:
        click.echo(f"-> review item {extraction.review_item_id}", err=True)
        sys.exit(1)
    click.echo(f"all {len(extraction.citations)} quotes located", err=True)


def _run_source(fetcher: Fetcher, allow_inactive: bool = False) -> bool:
    settings = _settings()
    sessions = session_factory(settings)
    result = run_source(
        fetcher,
        settings=settings,
        sessions=sessions,
        store=SnapshotStore(settings.snapshot_dir),
        gateway=lambda: Gateway(sessions, AnthropicProvider()),
        require_active=not allow_inactive,
        ocr=TesseractOcr(),
    )
    run = result.run
    click.echo(
        f"ingestion_run {run.run_id}: fetch {'ok' if run.ok else 'FAILED'}, "
        f"{len(run.changed)} changed, {len(run.found)} calls listed, {result.closed} closed"
    )
    if run.error:
        click.echo(run.error, err=True)
    for p in result.processed:
        if p.outcome == UNCHANGED:
            continue
        where = f"call {p.call_id}" if p.call_id else "no call"
        item = f", review item {p.review_item_id}" if p.review_item_id else ""
        detail = f": {p.detail}" if p.detail else ""
        line = f"  {p.outcome}: snapshots {list(p.found.snapshot_ids)}, {where}{item}{detail}"
        click.echo(line, err=p.outcome == ERROR)
    return result.ok


def _index() -> bool:
    settings = _settings()
    try:
        result = index_pending(session_factory(settings), LocalEmbedder(settings.model_dir))
    except Exception as exc:
        # Chunks written so far are kept; the next run embeds the rest.
        click.echo(f"index FAILED: {type(exc).__name__}: {exc}", err=True)
        return False
    click.echo(
        f"index: {result.chunks_written} chunks from {result.snapshots_chunked} snapshots, "
        f"{result.chunks_embedded} embedded"
    )
    return True


def _run(fetcher: Fetcher, allow_inactive: bool = False) -> None:
    settings = _settings()
    result = run_fetcher(
        fetcher,
        settings=settings,
        sessions=session_factory(settings),
        store=SnapshotStore(settings.snapshot_dir),
        require_active=not allow_inactive,
    )
    click.echo(
        f"ingestion_run {result.run_id}: {'ok' if result.ok else 'FAILED'}, "
        f"{len(result.changed)} changed"
    )
    if not result.ok:
        click.echo(result.error, err=True)
        sys.exit(1)


@click.group(help="What the review queue has decided.")
def review():
    pass


@review.command(
    "export-cases",
    help="Write an evaluation case for every rejected or edited item that has none yet.",
)
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to write into (default: GRANTS_REVIEW_CASES_DIR).",
)
def export_cases_command(out):
    """The nightly half of the review gate (docs/matching.md §6, roadmap P2 s34).

    Writes each case once and never again, so it is safe to run as often as cron
    likes. The files are pulled and committed by a person (docs/runbook.md §7).
    """
    out = out or Path(_settings().review_cases_dir)
    with session_factory(_settings())() as session:
        written = cases.export(session, out)
    for path in written:
        click.echo(f"wrote {path}")
    click.echo(f"{len(written)} new case(s) in {out}")


@review.command(
    "render-report",
    help="Write an approved report as the PDF the customer receives. Every check runs again.",
)
@click.argument("item_id", type=int)
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), required=True)
def render_report_command(item_id, out):
    with session_factory(_settings())() as session:
        item = session.get(ReviewQueueItem, item_id)
        if item is None:
            raise click.ClickException(f"no review item {item_id}")
        try:
            rendered = render.render(session, item)
        except render.RenderRefused as refused:
            raise click.ClickException(str(refused)) from refused
    out.write_bytes(rendered.pdf)
    click.echo(f"{out}: {rendered.pages} page(s), fonts {', '.join(rendered.fonts)}")
