"""The fetcher base class: one small subclass per source.

A subclass implements `crawl(ctx)`, calling `ctx.fetch()` for each thing it wants
-- usually a listing, then the items the listing links to. Everything else is the
base class's job: the polite client configured from the source's row, the
ingestion_run record, snapshot storage and change detection, source health, and
committing each snapshot as soon as it is stored, so a crawl that dies halfway
keeps what it already fetched.

Adding a source means a module in app/ingestion/sources/ and an entry in
config/sources.yaml, nothing else (CLAUDE.md). If a source needs more, the
abstraction is wrong and that is worth saying.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.ingestion.http import PoliteClient, Request, Response
from app.ingestion.snapshots import Recorded, Significant, SnapshotStore, all_bytes, record
from app.models import IngestionRun, SourceFeed, SourceHealth


class SourceNotRunnable(RuntimeError):
    pass


@dataclass(frozen=True)
class Fetched:
    response: Response
    recorded: Recorded

    @property
    def changed(self) -> bool:
        return self.recorded.changed


@dataclass
class CrawlContext:
    source: SourceFeed
    run: IngestionRun
    _session: Session
    _client: PoliteClient
    _store: SnapshotStore
    _significant: Significant = all_bytes
    changed: list[Fetched] = field(default_factory=list)

    def fetch(self, request: Request | str) -> Fetched:
        if isinstance(request, str):
            request = Request(request)
        response = self._client.fetch(request)
        recorded = record(self._session, self._store, self.source, response, self._significant)
        self.run.urls_seen += 1
        fetched = Fetched(response, recorded)
        if fetched.changed:
            self.run.urls_changed += 1
            self.changed.append(fetched)
        self._session.commit()
        return fetched


class Fetcher(ABC):
    slug: ClassVar[str]

    def significant(self, content: bytes) -> bytes:
        """Override to ignore parts of this source's pages that change on every request.

        See snapshots.without_aspnet_state. The default treats every byte as meaningful.
        """
        return content

    @abstractmethod
    def crawl(self, ctx: CrawlContext) -> None: ...


@dataclass(frozen=True)
class RunResult:
    run_id: int
    ok: bool
    changed: list[Fetched]
    error: str | None


def user_agent(settings: Settings) -> str:
    return f"grantbot/0.1 (+{settings.crawler_contact_url})"


def run_fetcher(
    fetcher: Fetcher,
    *,
    settings: Settings,
    sessions: sessionmaker[Session],
    store: SnapshotStore,
    client: PoliteClient | None = None,
    require_active: bool = True,
) -> RunResult:
    """Run one crawl. Failures are recorded and returned, not raised: cron must keep going.

    `require_active=False` is for a deliberate manual check of a source whose
    fetcher is still being written; scheduled runs never pass it.
    """
    with sessions() as session:
        source = session.scalars(select(SourceFeed).where(SourceFeed.slug == fetcher.slug)).first()
        if source is None:
            raise SourceNotRunnable(
                f"no source_feed {fetcher.slug!r}; run `flask ingest sync-sources`"
            )
        if require_active and not source.is_active:
            raise SourceNotRunnable(f"source {fetcher.slug!r} is not active in config/sources.yaml")

        run = IngestionRun(source_feed_id=source.id)
        session.add(run)
        health = session.get(SourceHealth, source.id) or SourceHealth(source_feed_id=source.id)
        session.add(health)
        health.last_attempt_at = func.now()
        session.commit()

        owns_client = client is None
        client = client or PoliteClient(
            user_agent(settings), min_interval_s=1 / float(source.rate_limit_rps)
        )
        significant = (
            all_bytes if type(fetcher).significant is Fetcher.significant else fetcher.significant
        )
        ctx = CrawlContext(source, run, session, client, store, significant)
        error = None
        try:
            fetcher.crawl(ctx)
        except Exception as exc:  # recorded on the run and the source's health, then reported
            session.rollback()
            error = f"{type(exc).__name__}: {exc}"[:2000]
        finally:
            if owns_client:
                client.close()

        run.finished_at = func.now()
        run.ok = error is None
        run.error = error
        if run.urls_seen:
            source.robots_checked_at = func.now()
        if error is None:
            health.last_success_at = func.now()
            health.consecutive_failures = 0
            health.last_error = None
        else:
            health.consecutive_failures = (health.consecutive_failures or 0) + 1
            health.last_error = error
        session.commit()
        return RunResult(run_id=run.id, ok=error is None, changed=ctx.changed, error=error)
