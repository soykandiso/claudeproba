"""Operator commands. Cron runs these as `docker compose exec web flask ...`."""

import sys

import click
from flask import Flask, current_app
from sqlalchemy import select

from app.db import session_factory
from app.ingestion.fetcher import CrawlContext, Fetcher, run_fetcher
from app.ingestion.snapshots import SnapshotStore, without_aspnet_state
from app.ingestion.source_config import load_sources, sync_sources
from app.ingestion.sources import fetchers
from app.models import SourceFeed


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
