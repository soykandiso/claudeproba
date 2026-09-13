"""Operator commands. Cron runs these as `docker compose exec web flask ...`."""

import sys

import click
from flask import Flask, current_app
from sqlalchemy import select

from app.ai.gateway import AnthropicProvider, Gateway, InvalidModelOutput
from app.db import session_factory
from app.ingestion.extract import Document, extract_call
from app.ingestion.fetcher import CrawlContext, Fetcher, run_fetcher
from app.ingestion.normalise.pdf import TesseractOcr
from app.ingestion.normalise.snapshot import normalise_snapshot, pending_snapshots
from app.ingestion.snapshots import SnapshotStore, without_aspnet_state
from app.ingestion.source_config import load_sources, sync_sources
from app.ingestion.sources import fetchers
from app.models import RawSnapshot, SourceFeed


def register_cli(app: Flask) -> None:
    app.cli.add_command(ingest)


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


@ingest.command("run", help="Crawl one source with its registered fetcher.")
@click.argument("slug")
def run_command(slug):
    available = fetchers()
    if slug not in available:
        raise click.ClickException(
            f"no fetcher for {slug!r}; have: {', '.join(available) or 'none'}"
        )
    _run(available[slug]())


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
            root = fetcher_cls().html_root(snapshot.url) if fetcher_cls else None
            outcome = normalise_snapshot(session, store, snapshot, ocr=ocr, html_root=root)
            session.commit()  # one document at a time: OCR is slow, keep what is done
            flag = f" -> review item {outcome.review_item_id}" if outcome.review_item_id else ""
            click.echo(f"snapshot {outcome.snapshot_id}: {outcome.detail}{flag}")
    if not snapshots:
        click.echo("nothing to normalise")


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
