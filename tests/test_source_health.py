"""Source health and alerting (roadmap P1 s14, docs/risks.md R1).

Acceptance: break a source deliberately and the alert leaves the app. Here AV is
broken for real -- its listing answers 404 through the pipeline -- and the alert is
the /fail ping healthchecks.io turns into an email, carrying the error. That the
email then reaches you is checked on the VPS with `flask ingest health --drill`
(docs/runbook.md §4).
"""

import datetime as dt
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import sessionmaker

from app import create_app
from app.ai.gateway import Gateway
from app.config import load_settings
from app.heartbeat import MAX_BODY, ping
from app.ingestion import pipeline
from app.ingestion.health import (
    FAILING,
    NOT_RUNNING,
    OK,
    QUIET,
    check_sources,
    run_health_check,
)
from app.ingestion.http import PoliteClient
from app.ingestion.snapshots import SnapshotStore
from app.ingestion.source_config import load_sources, sync_sources
from app.ingestion.sources.av import LISTING_URL, AvFetcher
from app.models import IngestionRun, SourceFeed, SourceHealth
from app.models.enums import AccessMethod
from tests.test_extract import ScriptedProvider
from tests.test_gateway import DATABASE_AVAILABLE

settings = load_settings()
TZ = ZoneInfo("Europe/Skopje")
NOW = dt.datetime(2026, 9, 16, 6, 30, tzinfo=dt.UTC)
HEALTH_URL = "https://hc-ping.com/test-health-check"


class Healthchecks:
    """healthchecks.io, recording the pings it receives."""

    def __init__(self, status: int = 200):
        self.pings: list[tuple[str, str]] = []
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.pings.append((str(request.url), request.content.decode("utf-8")))
        return httpx.Response(self.status, text="OK")

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


# -- the ping -----------------------------------------------------------------------------


def test_success_and_failure_go_to_the_two_healthchecks_endpoints():
    hc = Healthchecks()

    assert ping(HEALTH_URL, ok=True, body="all ok", transport=hc.transport) == "heartbeat sent (ok)"
    assert ping(HEALTH_URL + "/", ok=False, body="av failing", transport=hc.transport).endswith(
        "(fail)"
    )

    assert hc.pings == [(HEALTH_URL, "all ok"), (HEALTH_URL + "/fail", "av failing")]


def test_a_ping_that_cannot_be_delivered_is_reported_not_raised():
    def unreachable(request):
        raise httpx.ConnectError("no route to host")

    tries = []
    line = ping(
        HEALTH_URL,
        ok=False,
        body="x",
        transport=httpx.MockTransport(unreachable),
        sleep=tries.append,
    )

    assert line.startswith("heartbeat FAILED after 3 attempts: ConnectError")
    assert tries == [1, 2]
    assert ping(HEALTH_URL, ok=True, body="x", transport=Healthchecks(500).transport).endswith(
        "HTTP 500"
    )


def test_no_url_is_said_plainly_and_a_long_body_is_cut():
    assert ping(None, ok=False, body="x") == "heartbeat not configured"
    assert ping("", ok=True, body="x") == "heartbeat not configured"

    hc = Healthchecks()
    ping(HEALTH_URL, ok=False, body="é" * (MAX_BODY * 2), transport=hc.transport)
    [(_, body)] = hc.pings
    assert len(body) <= MAX_BODY and body.endswith("[... truncated]")


def test_production_refuses_to_judge_sources_with_nowhere_to_send_the_alert():
    app = create_app(load_settings(env="production", heartbeat_health_url=None))

    with app.app_context():
        result = app.test_cli_runner().invoke(args=["ingest", "health"])

    assert result.exit_code != 0 and "GRANTS_HEARTBEAT_HEALTH_URL is not set" in result.output


def test_a_drill_with_nowhere_to_go_fails():
    app = create_app(load_settings(heartbeat_health_url=None))

    with app.app_context():
        result = app.test_cli_runner().invoke(args=["ingest", "health", "--drill"])

    assert result.exit_code == 1 and "heartbeat not configured" in result.output


# -- the judgement ------------------------------------------------------------------------

needs_database = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)


@pytest.fixture
def sessions():
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    with factory() as s:
        sync_sources(s, load_sources())
        # Only the sources a test creates or activates are judged, from a clean slate.
        s.execute(update(SourceFeed).values(is_active=False))
        s.execute(update(SourceHealth).values(is_alerting=False))
        s.commit()
    yield factory
    transaction.rollback()
    connection.close()
    engine.dispose()


def source(sessions, slug="test-health", *, active_for=dt.timedelta(days=100), sla_days=30):
    with sessions() as s:
        feed = SourceFeed(
            slug=slug, name_mk="Тест", name_en="Test", institution="Test",
            base_url="https://gov.example", access_method=AccessMethod.API,
            expected_cadence=dt.timedelta(days=7), staleness_sla=dt.timedelta(days=sla_days),
            is_active=True, created_at=NOW - active_for,
        )  # fmt: skip
        s.add(feed)
        s.flush()
        s.add(SourceHealth(source_feed_id=feed.id, last_new_item_at=NOW - dt.timedelta(days=2)))
        s.commit()
        return feed.id


def runs(sessions, feed_id, *history):
    """(hours ago, ok, error) per run."""
    with sessions() as s:
        for hours, ok, error in history:
            started = NOW - dt.timedelta(hours=hours)
            s.add(
                IngestionRun(
                    source_feed_id=feed_id,
                    started_at=started,
                    finished_at=started + dt.timedelta(minutes=3),
                    ok=ok,
                    error=error,
                )
            )
        s.commit()


def judged(sessions, now=NOW):
    with sessions() as s:
        states = {state.slug: state for state in check_sources(s, now, TZ)}
        s.commit()
    return states


@needs_database
def test_a_source_that_ran_well_this_morning_is_ok(sessions):
    feed = source(sessions)
    runs(sessions, feed, (30, True, None), (6, True, None))

    state = judged(sessions)["test-health"]

    assert state.status == OK and state.detail == "last success 16.09.2026 02:30"


@needs_database
def test_one_bad_night_is_a_note_with_the_time_it_becomes_an_alert(sessions):
    feed = source(sessions)
    runs(sessions, feed, (20, True, None), (2, False, "FetchError: HTTP 503"))

    state = judged(sessions)["test-health"]

    assert state.status == OK
    assert "last run failed (FetchError: HTTP 503); alerts at 16.09.2026 18:30" in state.detail


@needs_database
def test_thirty_hours_without_a_successful_run_is_failing(sessions):
    feed = source(sessions)
    runs(
        sessions,
        feed,
        (40, True, None),
        (36, False, "RobotsDisallowed: robots.txt disallows"),
        (4, False, "processing failed for 1 calls:\nTypeError: no API key"),
    )

    state = judged(sessions)["test-health"]

    assert state.status == FAILING
    assert state.detail == (
        "last success 14.09.2026 16:30; 2 failed runs since; "
        "processing failed for 1 calls: TypeError: no API key"
    )


@needs_database
def test_a_new_source_that_never_succeeded_fails_after_thirty_hours(sessions):
    feed = source(sessions, active_for=dt.timedelta(days=2))
    runs(sessions, feed, (31, False, "FetchError: timeout"), (1, False, "FetchError: timeout"))

    assert judged(sessions)["test-health"].status == FAILING
    assert judged(sessions)["test-health"].detail.startswith("never succeeded; 2 failed runs")


@needs_database
def test_a_source_nobody_runs_is_not_running(sessions):
    stopped = source(sessions, "test-stopped")
    runs(sessions, stopped, (31, True, None))
    source(sessions, "test-never", active_for=dt.timedelta(hours=31))
    source(sessions, "test-just-added", active_for=dt.timedelta(hours=1))

    states = judged(sessions)

    assert states["test-stopped"].status == NOT_RUNNING
    assert states["test-never"].status == NOT_RUNNING
    assert states["test-never"].detail.startswith("never run")
    assert states["test-just-added"].status == OK


@needs_database
def test_runs_that_succeed_but_find_nothing_new_past_the_sla_are_quiet(sessions):
    feed = source(sessions, sla_days=30)
    runs(sessions, feed, (3, True, None))
    with sessions() as s:
        s.get(SourceHealth, feed).last_new_item_at = NOW - dt.timedelta(days=31)
        s.commit()

    state = judged(sessions)["test-health"]

    assert state.status == QUIET
    assert state.detail.startswith("last new call 16.08.2026 08:30, SLA 30 days")


@needs_database
def test_an_alert_is_new_once_and_clears_when_the_source_recovers(sessions):
    feed = source(sessions)
    runs(sessions, feed, (40, True, None), (5, False, "FetchError: HTTP 404"))

    first, second = judged(sessions)["test-health"], judged(sessions)["test-health"]
    assert first.newly_alerting and second.alerting and not second.newly_alerting

    runs(sessions, feed, (1, True, None))
    assert not judged(sessions)["test-health"].alerting
    with sessions() as s:
        assert s.get(SourceHealth, feed).is_alerting is False


# -- the report ---------------------------------------------------------------------------


def health_check(sessions, hc, now=NOW):
    return run_health_check(sessions, url=HEALTH_URL, now=now, tz=TZ, transport=hc.transport)


@needs_database
def test_all_ok_is_a_success_ping_with_the_report(sessions):
    runs(sessions, source(sessions), (6, True, None))
    hc = Healthchecks()

    result = health_check(sessions, hc)

    assert not result.alerting and result.heartbeat == ["heartbeat sent (ok)"]
    [(url, body)] = hc.pings
    assert url == HEALTH_URL and body.startswith("all 1 active sources ok (16.09.2026 08:30")


@needs_database
def test_a_second_problem_while_already_alerting_is_announced_too(sessions):
    first = source(sessions, "test-first")
    second = source(sessions, "test-second")
    runs(sessions, first, (40, True, None), (2, False, "FetchError: HTTP 404"))
    runs(sessions, second, (6, True, None))
    health_check(sessions, Healthchecks())

    hc = Healthchecks()
    health_check(sessions, hc)
    assert [url for url, _ in hc.pings] == [HEALTH_URL + "/fail"]  # nothing new: no re-arm

    runs(sessions, second, (1, False, "FetchError: timeout"))
    later = NOW + dt.timedelta(hours=26)
    hc = Healthchecks()
    health_check(sessions, hc, now=later)

    assert [url for url, _ in hc.pings] == [HEALTH_URL, HEALTH_URL + "/fail"]
    assert "FAILING (new)  test-second" in hc.pings[1][1]


# -- acceptance: break a source for real --------------------------------------------------


@needs_database
def test_a_broken_source_sends_an_alert_out_of_the_app_with_its_error(sessions, tmp_path):
    with sessions() as s:
        av = s.scalars(select(SourceFeed).where(SourceFeed.slug == "av")).one()
        av.is_active = True
        s.execute(delete(IngestionRun).where(IngestionRun.source_feed_id == av.id))
        s.commit()
        av_id = s.scalar(select(SourceFeed.id).where(SourceFeed.slug == "av"))
        started = s.scalar(select(func.now()))  # this transaction's clock
    # It last worked 31 hours before this transaction began.
    with sessions() as s:
        s.add(
            IngestionRun(source_feed_id=av_id, started_at=started - dt.timedelta(hours=31), ok=True)
        )
        s.commit()

    def moved(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: *.pdf\n")
        assert str(request.url) == LISTING_URL
        return httpx.Response(404, text="<html>Not found</html>")

    broken = pipeline.run_source(
        AvFetcher(),
        settings=settings,
        sessions=sessions,
        store=SnapshotStore(tmp_path),
        gateway=lambda: Gateway(sessions, ScriptedProvider()),
        client=PoliteClient(
            "grantbot/test", min_interval_s=0, transport=httpx.MockTransport(moved)
        ),
    )
    assert not broken.ok

    hc = Healthchecks()
    result = run_health_check(
        sessions,
        url=HEALTH_URL,
        now=started + dt.timedelta(minutes=5),
        tz=TZ,
        transport=hc.transport,
    )

    assert result.alerting
    [(url, body)] = hc.pings
    assert url == HEALTH_URL + "/fail"
    assert "FAILING (new)  av: last success" in body
    assert f"{LISTING_URL} returned HTTP 404" in body
    assert "docs/runbook.md" in body
