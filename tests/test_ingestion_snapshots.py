"""Snapshot store, change detector and fetcher runs against a real PostgreSQL.

Roadmap P1 s8 acceptance: fetching one URL twice creates one snapshot row, the
bytes land in the store, and the second fetch queues nothing for analysis.
"""

import datetime as dt

import httpx
import psycopg
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import load_settings
from app.ingestion.fetcher import CrawlContext, Fetcher, SourceNotRunnable, run_fetcher
from app.ingestion.http import PoliteClient
from app.ingestion.snapshots import CorruptSnapshot, SnapshotStore, without_aspnet_state
from app.ingestion.source_config import load_sources, sync_sources
from app.models import IngestionRun, RawSnapshot, SourceFeed, SourceHealth
from app.models.enums import AccessMethod

settings = load_settings()

try:
    with psycopg.connect(settings.database_url, connect_timeout=2):
        DATABASE_AVAILABLE = True
except Exception:
    DATABASE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)

SLUG = "test-source"


class MutableSite:
    """Serves whatever `pages` currently says, so a test can change a page between runs."""

    def __init__(self):
        self.pages = {"/calls": b"<html>call A</html>", "/call/1": b"<html>detail 1</html>"}
        self.fetched: list[str] = []

    def handler(self, request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        self.fetched.append(request.url.path)
        if request.url.path not in self.pages:
            return httpx.Response(500, text="broken")
        return httpx.Response(200, content=self.pages[request.url.path])


class ListingThenDetail(Fetcher):
    slug = SLUG

    def crawl(self, ctx: CrawlContext) -> None:
        ctx.fetch("https://gov.example/calls")
        ctx.fetch("https://gov.example/call/1")


@pytest.fixture
def sessions():
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    with factory() as s:
        s.add(
            SourceFeed(
                slug=SLUG,
                name_mk="Тест",
                name_en="Test",
                institution="Test",
                base_url="https://gov.example",
                access_method=AccessMethod.HTML,
                expected_cadence=dt.timedelta(days=7),
                staleness_sla=dt.timedelta(days=30),
            )
        )
        s.commit()
    yield factory
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def site():
    return MutableSite()


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path)


def crawl(sessions, store, site, fetcher=None, **kwargs):
    client = PoliteClient(
        "grantbot/test", min_interval_s=0, transport=httpx.MockTransport(site.handler)
    )
    return run_fetcher(
        fetcher or ListingThenDetail(),
        settings=settings,
        sessions=sessions,
        store=store,
        client=client,
        **kwargs,
    )


def health(s):
    return s.scalars(select(SourceHealth).join(SourceFeed).where(SourceFeed.slug == SLUG)).one()


def snapshots(sessions, url="https://gov.example/calls"):
    with sessions() as s:
        return s.scalars(
            select(RawSnapshot).where(RawSnapshot.url == url).order_by(RawSnapshot.id)
        ).all()


def stored_files(store):
    return sorted(p for p in store.root.rglob("*") if p.is_file())


def test_fetching_unchanged_pages_twice_creates_one_row_per_page(sessions, store, site):
    first = crawl(sessions, store, site)
    second = crawl(sessions, store, site)

    assert first.ok and second.ok
    assert len(first.changed) == 2
    assert second.changed == [], "nothing new to analyse, so no tokens are spent"
    assert len(snapshots(sessions)) == 1
    assert len(stored_files(store)) == 2


def test_the_bytes_in_the_store_are_exactly_what_was_served(sessions, store, site):
    crawl(sessions, store, site)

    [snap] = snapshots(sessions)
    assert store.get(snap.storage_key) == b"<html>call A</html>"
    assert snap.storage_key == f"snapshots/{SLUG}/{snap.content_sha256}"
    assert snap.byte_length == len(b"<html>call A</html>")


def test_an_unchanged_page_moves_last_seen_at(sessions, store, site):
    crawl(sessions, store, site)
    [before] = snapshots(sessions)
    crawl(sessions, store, site)
    [after] = snapshots(sessions)

    assert after.last_seen_at > before.last_seen_at
    assert after.fetched_at == before.fetched_at


def test_a_changed_page_creates_a_new_snapshot(sessions, store, site):
    crawl(sessions, store, site)
    site.pages["/calls"] = b"<html>call A, call B</html>"
    result = crawl(sessions, store, site)

    assert [f.response.request.url for f in result.changed] == ["https://gov.example/calls"]
    assert len(snapshots(sessions)) == 2


def test_a_page_that_reverts_is_current_again_without_a_duplicate(sessions, store, site):
    crawl(sessions, store, site)  # A
    site.pages["/calls"] = b"<html>call B</html>"
    crawl(sessions, store, site)  # B
    site.pages["/calls"] = b"<html>call A</html>"
    reverted = crawl(sessions, store, site)  # A again
    again = crawl(sessions, store, site)  # still A

    assert len(snapshots(sessions)) == 2
    assert len(reverted.changed) == 1, "the revert is a change worth re-reading"
    assert again.changed == [], "and after that it is unchanged, not changed on every run"


def test_a_successful_run_is_recorded_with_health(sessions, store, site):
    result = crawl(sessions, store, site)

    with sessions() as s:
        run = s.get(IngestionRun, result.run_id)
        h = health(s)
        assert run.ok and run.urls_seen == 2 and run.urls_changed == 2 and run.finished_at
        assert h.last_success_at and h.consecutive_failures == 0


def test_a_failed_run_keeps_what_it_fetched_and_counts_the_failure(sessions, store, site):
    del site.pages["/call/1"]

    first = crawl(sessions, store, site)
    second = crawl(sessions, store, site)

    assert not first.ok and "500" in first.error
    assert len(snapshots(sessions)) == 1, "the listing fetched before the failure was kept"
    with sessions() as s:
        h = health(s)
        assert h.consecutive_failures == 2
        assert "500" in h.last_error
        assert s.get(IngestionRun, second.run_id).ok is False


def test_an_inactive_source_is_not_crawled_by_schedule(sessions, store, site):
    with sessions() as s:
        s.scalars(select(SourceFeed).where(SourceFeed.slug == SLUG)).one().is_active = False
        s.commit()

    with pytest.raises(SourceNotRunnable):
        crawl(sessions, store, site)
    assert crawl(sessions, store, site, require_active=False).ok


def test_a_tampered_snapshot_file_is_detected(sessions, store, site):
    crawl(sessions, store, site)
    [snap] = snapshots(sessions)
    (store.root / snap.storage_key).write_bytes(b"<html>edited</html>")

    with pytest.raises(CorruptSnapshot):
        store.get(snap.storage_key)


def test_sources_yaml_syncs_and_is_idempotent(sessions):
    entries = load_sources()

    with sessions() as s:
        sync_sources(s, entries)
        second = sync_sources(s, entries)
        s.commit()
        rows = {r.slug: r for r in s.scalars(select(SourceFeed))}

    assert second == [], "a second sync with an unchanged file changes nothing"
    assert {e.slug for e in entries} <= rows.keys()
    assert rows["av"].access_method == AccessMethod.API
    assert rows["av"].staleness_sla == dt.timedelta(days=45)
    assert rows[SLUG].is_active is False, (
        "a source missing from the file is deactivated, not deleted"
    )


ASPX = (
    b'<form><input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="%s" />'
    b"<ul><li>Call 820</li></ul></form>"
)


class AspNetListing(Fetcher):
    slug = SLUG

    def significant(self, content: bytes) -> bytes:
        return without_aspnet_state(content)

    def crawl(self, ctx: CrawlContext) -> None:
        ctx.fetch("https://gov.example/calls")


def test_a_regenerated_viewstate_alone_is_not_a_change(sessions, store, site):
    """The av.gov.mk behaviour seen live on 13.09.2026."""
    site.pages["/calls"] = ASPX % b"6HFuba"
    crawl(sessions, store, site, AspNetListing())
    site.pages["/calls"] = ASPX % b"jyLzpL"
    second = crawl(sessions, store, site, AspNetListing())

    assert second.changed == []
    [snap] = snapshots(sessions)
    assert b"6HFuba" in store.get(snap.storage_key), "the stored bytes are what was first served"


def test_real_content_behind_a_viewstate_is_still_a_change(sessions, store, site):
    site.pages["/calls"] = ASPX % b"6HFuba"
    crawl(sessions, store, site, AspNetListing())
    site.pages["/calls"] = (ASPX % b"jyLzpL").replace(b"Call 820", b"Call 821")

    assert len(crawl(sessions, store, site, AspNetListing()).changed) == 1
    assert len(snapshots(sessions)) == 2


def test_without_a_significance_rule_every_byte_counts(sessions, store, site):
    site.pages["/calls"] = ASPX % b"6HFuba"
    crawl(sessions, store, site)
    site.pages["/calls"] = ASPX % b"jyLzpL"

    assert len(crawl(sessions, store, site).changed) == 1
