"""Fill the DEVELOPMENT database's review queue from the captured fixtures. Refuses production.

No network and no model: the real pipeline runs over tests/fixtures (AV 819, EU EdTech
and COSME topics) with the hand-written replies in tests/cassettes. Leaves two calls
to approve and one extraction whose quotes are not found, so every /admin screen has
something real to show.

    PYTHONPATH=. uv run python ops/dev/seed_review_queue.py

Run it again after a change to either document and the pipeline reports "unchanged".
Snapshot bytes go to a throwaway directory: /admin reads text from the database.
"""

import datetime as dt
import tempfile

import httpx

from app.ai.gateway import Gateway
from app.config import load_settings
from app.db import session_factory
from app.ingestion import pipeline
from app.ingestion.http import PoliteClient
from app.ingestion.snapshots import SnapshotStore
from app.ingestion.source_config import load_sources, sync_sources
from app.ingestion.sources.av import AvFetcher
from app.ingestion.sources.eu_portal import EuPortalFetcher
from tests.test_extract import ScriptedProvider
from tests.test_extract_schema import cassette
from tests.test_pipeline import AvSite
from tests.test_source_eu_portal import COSME, EuPortal, result


def main() -> None:
    settings = load_settings()
    if settings.is_production:
        raise SystemExit("refusing to seed a production database")
    sessions = session_factory(settings)
    store = SnapshotStore(tempfile.mkdtemp(prefix="seed-snapshots-"))
    with sessions() as s:
        print("sources:", sync_sources(s, load_sources()) or "unchanged")
        s.commit()

    def client(handler):
        return PoliteClient(
            "grantbot/dev-seed", min_interval_s=0, transport=httpx.MockTransport(handler)
        )

    av = pipeline.run_source(
        AvFetcher(),
        settings=settings,
        sessions=sessions,
        store=store,
        gateway=lambda: Gateway(sessions, ScriptedProvider(cassette("av-measure-819"))),
        client=client(AvSite().handler),
        now=lambda: dt.datetime(2026, 8, 10, tzinfo=dt.UTC),
    )
    print("av:", [(p.outcome, p.review_item_id) for p in av.processed])

    portal = EuPortal()
    # COSME listed as still open, extracted with the EdTech reply: its quotes are not there.
    portal.pages["frameworkProgramme"][1] = result(COSME, "2027-02-05T00:00:00.000+0000")
    edtech = cassette("eu-digital-2026-skills-10-edtech")
    eu = pipeline.run_source(
        EuPortalFetcher(today=lambda: dt.date(2026, 9, 16)),
        settings=settings,
        sessions=sessions,
        store=store,
        gateway=lambda: Gateway(sessions, ScriptedProvider(edtech, edtech)),
        client=client(portal.handler),
    )
    print("eu-portal:", [(p.outcome, p.review_item_id) for p in eu.processed])


if __name__ == "__main__":
    main()
