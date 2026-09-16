"""Is each source still bringing in calls? (docs/risks.md R1, roadmap P1 s14)

A silently dead scraper is the primary failure mode of this business. `flask ingest
health` runs this once a day, independently of the ingestion run that may itself be
broken, and reports to healthchecks.io (app/heartbeat.py), which emails.

Each active source is in exactly one state:

- **failing** -- its latest run failed and no run has succeeded for FAILING_AFTER.
  A run fails when the fetch fails (blocked, moved, changed shape) or when calls
  could not be processed (provider down, key expired). Cron retries a failed
  source every 4 hours, so 30 hours is about six attempts: long enough that a
  ministry's bad afternoon is not an alert, short enough that you hear the next
  morning.
- **not_running** -- no run has started for NOT_RUN_AFTER: cron is not running
  it, or it is active in config/sources.yaml with no fetcher.
- **quiet** -- runs succeed, but no new call for longer than the source's
  `staleness_sla`. The slow failure: a listing that still parses but no longer
  lists anything, a scope that stopped matching. The SLAs are generous where
  calls are seasonal (config/sources.yaml), so a quiet alert asks you to look at
  the source's site, not necessarily to fix code.
- **ok**, possibly with a note that its last run failed and when that becomes an
  alert.

`source_health.is_alerting` records the state, so the command can tell a new
problem from one you have already been told about.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.heartbeat import ping
from app.models import IngestionRun, SourceFeed, SourceHealth

FAILING_AFTER = dt.timedelta(hours=30)
NOT_RUN_AFTER = dt.timedelta(hours=30)

OK, FAILING, NOT_RUNNING, QUIET = "ok", "failing", "not_running", "quiet"


@dataclass(frozen=True)
class SourceState:
    slug: str
    status: str
    detail: str
    was_alerting: bool = False

    @property
    def alerting(self) -> bool:
        return self.status != OK

    @property
    def newly_alerting(self) -> bool:
        return self.alerting and not self.was_alerting


def check_sources(session: Session, now: dt.datetime, tz: ZoneInfo) -> list[SourceState]:
    """Judge every active source at `now`, and record which are alerting. Does not commit."""
    states = []
    for source in session.scalars(
        select(SourceFeed)
        .where(SourceFeed.is_active)
        .order_by(SourceFeed.priority, SourceFeed.slug)
    ):
        health = session.get(SourceHealth, source.id)
        if health is None:
            health = SourceHealth(source_feed_id=source.id, is_alerting=False)
            session.add(health)
        status, detail = _judge(session, source, health, now, tz)
        was = bool(health.is_alerting)
        health.is_alerting = status != OK
        states.append(SourceState(source.slug, status, detail, was))
    session.flush()
    return states


def _judge(session, source: SourceFeed, health: SourceHealth, now, tz) -> tuple[str, str]:
    latest = _latest_run(session, source.id)
    last_ok = session.scalar(
        select(func.max(IngestionRun.started_at)).where(
            IngestionRun.source_feed_id == source.id, IngestionRun.ok.is_(True)
        )
    )

    if latest is None:
        if now - source.created_at > NOT_RUN_AFTER:
            return NOT_RUNNING, f"never run, active since {_when(source.created_at, tz)}"
        return OK, "not run yet"
    if now - latest.started_at > NOT_RUN_AFTER:
        return NOT_RUNNING, f"last run started {_when(latest.started_at, tz)}"

    if latest.ok is not True:
        first = session.scalar(
            select(func.min(IngestionRun.started_at)).where(
                IngestionRun.source_feed_id == source.id
            )
        )
        since = last_ok or first
        error = _first_line(latest.error) or (
            "still running, or stopped without finishing"
            if latest.finished_at is None
            else "failed without an error message"
        )
        if now - since > FAILING_AFTER:
            # Counted from ingestion_run, not source_health.consecutive_failures, which
            # counts only fetch failures: a run whose calls could not be processed failed too.
            failed = session.scalar(
                select(func.count())
                .select_from(IngestionRun)
                .where(
                    IngestionRun.source_feed_id == source.id,
                    IngestionRun.ok.is_not(True),
                    IngestionRun.started_at >= since,
                )
            )
            succeeded = f"last success {_when(last_ok, tz)}" if last_ok else "never succeeded"
            return FAILING, f"{succeeded}; {failed} failed runs since; {error}"
        alert_at = _when(since + FAILING_AFTER, tz)
        note = f"last run failed ({error}); alerts at {alert_at} unless a run succeeds"
        return OK, note

    reference = health.last_new_item_at or source.created_at
    if now - reference > source.staleness_sla:
        what = "last new call" if health.last_new_item_at else "no new call since active"
        return QUIET, (
            f"{what} {_when(reference, tz)}, SLA {source.staleness_sla.days} days; "
            f"last success {_when(last_ok, tz)}"
        )
    return OK, f"last success {_when(last_ok, tz)}"


def _latest_run(session: Session, source_id: uuid.UUID) -> IngestionRun | None:
    return session.scalars(
        select(IngestionRun)
        .where(IngestionRun.source_feed_id == source_id)
        .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
        .limit(1)
    ).first()


def _when(moment: dt.datetime | None, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%d.%m.%Y %H:%M") if moment else "never"


def _first_line(text: str | None) -> str:
    """The error's opening line, and the next one when the first only introduces it."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    shown = " ".join(lines[:2]) if lines[0].endswith(":") and len(lines) > 1 else lines[0]
    return shown[:300]


def report(states: list[SourceState], now: dt.datetime, tz: ZoneInfo) -> str:
    """The text you read in the alert email and in the command's log."""
    alerting = [s for s in states if s.alerting]
    head = (
        f"{len(alerting)} of {len(states)} active sources need attention"
        if alerting
        else f"all {len(states)} active sources ok"
    )
    lines = [f"{head} ({_when(now, tz)} {tz.key})", ""]
    for state in alerting + [s for s in states if not s.alerting]:
        marker = state.status.upper() if state.alerting else "ok"
        new = " (new)" if state.newly_alerting else ""
        lines.append(f"{marker}{new}  {state.slug}: {state.detail}")
    if alerting:
        lines += ["", "What to do: docs/runbook.md, 'A source alert'."]
    return "\n".join(lines)


@dataclass(frozen=True)
class HealthResult:
    states: list[SourceState]
    text: str
    heartbeat: list[str]

    @property
    def alerting(self) -> bool:
        return any(state.alerting for state in self.states)


def run_health_check(
    sessions: sessionmaker[Session],
    *,
    url: str | None,
    now: dt.datetime,
    tz: ZoneInfo,
    transport: httpx.BaseTransport | None = None,
) -> HealthResult:
    """Judge, record, and report to the health check. What `flask ingest health` runs."""
    with sessions() as session:
        states = check_sources(session, now, tz)
        session.commit()
    text = report(states, now, tz)
    alerting = any(state.alerting for state in states)

    heartbeat = []
    if any(state.was_alerting for state in states) and any(s.newly_alerting for s in states):
        # healthchecks.io emails only when a check changes state. It is already
        # down for the earlier problem, so a second failure would arrive in
        # silence: bring it up for a moment so this one is announced too.
        heartbeat.append(
            ping(url, ok=True, body="re-arming: a new source problem follows", transport=transport)
        )
    heartbeat.append(ping(url, ok=not alerting, body=text, transport=transport))
    return HealthResult(states, text, heartbeat)
