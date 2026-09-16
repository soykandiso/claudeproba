"""The AV fetcher end to end: crawl → snapshot → normalise → extract → unpublished call.

Roadmap P1 s11 acceptance, with AV in the slot FITR could not take (docs/sources.md
§6.1): a newly published call is in the database with a snapshot and working
citations, and every path that cannot vouch for a call ends in the review queue.

The site is the reconnaissance fixtures served from a mock transport; the model
is the hand-written reply in tests/cassettes/extract_call/av-measure-819.json.
"""

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.ai.gateway import Gateway
from app.config import load_settings
from app.ingestion import pipeline
from app.ingestion.http import PoliteClient
from app.ingestion.snapshots import SnapshotStore
from app.ingestion.source_config import load_sources, sync_sources
from app.ingestion.sources.av import DETAIL_URL, LISTING_URL, PUBLIC_URL, AvFetcher
from app.models import (
    Call,
    CallDocument,
    EligibilityCriterion,
    IngestionRun,
    Programme,
    RawSnapshot,
    ReviewQueueItem,
    SourceFeed,
    SourceHealth,
)
from app.models.enums import CallStatus, CriterionKind
from tests.test_extract import ScriptedProvider
from tests.test_extract_schema import cassette
from tests.test_gateway import DATABASE_AVAILABLE

settings = load_settings()

pytestmark = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)

FIXTURES = Path(__file__).parent / "fixtures" / "av"
BEFORE_DEADLINE = dt.datetime(2026, 8, 10, 9, 0, tzinfo=dt.UTC)  # 819 closes 21.08.2026


class AvSite:
    """av.gov.mk as captured, with 819 as the one open call for employers."""

    def __init__(self):
        self.listing = json.loads((FIXTURES / "measures-list.json").read_bytes())
        self.set_open(819)
        self.details = {819: (FIXTURES / "measure-819-business-mk.json").read_bytes()}

    def set_open(self, *ids: int) -> None:
        for item in self.listing["d"]:
            item["ActiveMeasureIsArchived"] = item["AnnouncementId"] not in ids

    def change_text(self, announcement_id: int, old: str, new: str) -> None:
        data = json.loads(self.details[announcement_id])
        assert old in data["d"]
        data["d"] = data["d"].replace(old, new)
        self.details[announcement_id] = json.dumps(data, ensure_ascii=False).encode()

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: *.pdf\n")
        if url == LISTING_URL:
            return httpx.Response(200, json=self.listing)
        if url == DETAIL_URL:
            detail_id = json.loads(request.content)["detailId"]
            return httpx.Response(
                200, content=self.details[detail_id], headers={"content-type": "application/json"}
            )
        return httpx.Response(404)


class FailingProvider:
    def __init__(self):
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        raise ConnectionError("provider unreachable")


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
        av = s.scalars(select(SourceFeed).where(SourceFeed.slug == "av")).one()
        av.is_active = True
        # The development database may hold real rows; this test starts from none.
        s.execute(delete(ReviewQueueItem))
        s.execute(delete(Call).where(Call.source_feed_id == av.id))
        s.execute(delete(RawSnapshot).where(RawSnapshot.source_feed_id == av.id))
        s.commit()
    yield factory
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def site():
    return AvSite()


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path)


def run(sessions, store, site, provider, now=BEFORE_DEADLINE):
    client = PoliteClient(
        "grantbot/test", min_interval_s=0, transport=httpx.MockTransport(site.handler)
    )
    return pipeline.run_source(
        AvFetcher(),
        settings=settings,
        sessions=sessions,
        store=store,
        gateway=lambda: Gateway(sessions, provider),
        client=client,
        now=lambda: now,
    )


def outcomes(result):
    return [p.outcome for p in result.processed]


def items(sessions):
    with sessions() as s:
        return s.scalars(select(ReviewQueueItem).order_by(ReviewQueueItem.id)).all()


def calls(sessions):
    with sessions() as s:
        return s.scalars(select(Call).join(SourceFeed).where(SourceFeed.slug == "av")).all()


def criteria(sessions, call_id):
    with sessions() as s:
        return s.scalars(
            select(EligibilityCriterion)
            .where(EligibilityCriterion.call_id == call_id)
            .order_by(EligibilityCriterion.is_approved.desc(), EligibilityCriterion.quote_start)
        ).all()


def test_a_new_call_is_written_unpublished_with_every_criterion_cited(sessions, store, site):
    result = run(sessions, store, site, ScriptedProvider(cassette("av-measure-819")))

    assert result.ok and outcomes(result) == [pipeline.CREATED] and result.closed == 0
    [call] = calls(sessions)
    assert call.title_mk.endswith("мерката 4. Практикантство")
    assert not call.is_published and call.status == CallStatus.OPEN
    assert call.canonical_url == PUBLIC_URL
    assert call.published_at == dt.date(2026, 8, 5)
    # A date without a time is the end of that day in Skopje (UTC+2 in August).
    assert call.deadline_at == dt.datetime(2026, 8, 21, 21, 59, 59, tzinfo=dt.UTC)
    assert call.allowed_entity_types == []  # filled only from approved criteria (P1 s15)

    with sessions() as s:
        snapshot = s.get(RawSnapshot, call.primary_snapshot_id)
        assert snapshot.url.endswith('#POST {"detailId":819}')
        [document] = s.scalars(select(CallDocument).where(CallDocument.call_id == call.id)).all()
        assert document.snapshot_id == snapshot.id and document.is_primary
        assert s.get(Programme, call.programme_id).is_singleton

    rows = criteria(sessions, call.id)
    assert len(rows) == 3 and not any(row.is_approved for row in rows)
    for row in rows:
        assert row.snapshot_id == snapshot.id and row.source_url == PUBLIC_URL
        assert snapshot.normalised_text[row.quote_start : row.quote_end] == row.source_quote
        assert row.prompt_version.startswith("extract_call/")
    hard = [row for row in rows if row.kind == CriterionKind.HARD_STRUCTURED]
    assert [(r.field, r.operator, r.value_json) for r in hard] == [
        ("entity_type", "not_in", {"values": ["municipality"]})
    ]

    [item] = items(sessions)
    assert item.call_id == call.id and item.payload["stage"] == "approve_call"
    assert item.payload["listing"]["listed_to"] == "31.08.2026"  # the listing disagrees: 21.08
    assert item.payload["citations"]["deadline"]["source_quote"].startswith("можат да аплицираат")

    with sessions() as s:
        ingestion_run = s.get(IngestionRun, result.run.run_id)
        assert (ingestion_run.items_created, ingestion_run.queued_for_review) == (1, 1)
        assert s.get(SourceHealth, call.source_feed_id).last_new_item_at is not None


def test_a_second_run_over_unchanged_bytes_spends_nothing(sessions, store, site):
    provider = ScriptedProvider(cassette("av-measure-819"))
    run(sessions, store, site, provider)
    [before] = calls(sessions)

    result = run(sessions, store, site, provider)

    assert outcomes(result) == [pipeline.UNCHANGED] and result.run.changed == []
    assert len(provider.requests) == 1 and len(items(sessions)) == 1
    [after] = calls(sessions)
    assert after.last_verified_at > before.last_verified_at


def test_a_changed_document_unpublishes_and_keeps_approved_criteria(sessions, store, site):
    reply = cassette("av-measure-819")
    run(sessions, store, site, ScriptedProvider(reply))
    [call] = calls(sessions)
    with sessions() as s:
        s.get(Call, call.id).is_published = True
        approved = criteria(sessions, call.id)[0]
        row = s.get(EligibilityCriterion, approved.id)
        row.is_approved = True
        s.commit()

    site.change_text(819, "12.000,00 денари", "13.000,00 денари")
    result = run(sessions, store, site, ScriptedProvider(reply))

    assert outcomes(result) == [pipeline.UPDATED]
    [updated] = calls(sessions)
    assert updated.id == call.id and not updated.is_published
    assert updated.primary_snapshot_id != call.primary_snapshot_id
    rows = criteria(sessions, call.id)
    assert [r.id for r in rows if r.is_approved] == [approved.id]
    assert len([r for r in rows if not r.is_approved]) == 3
    assert {r.snapshot_id for r in rows if not r.is_approved} == {updated.primary_snapshot_id}
    item = items(sessions)[-1]
    assert item.priority == pipeline.PRIORITY_WAS_PUBLISHED
    assert "was published" in item.reason and "1 previously approved" in item.reason
    with sessions() as s:
        documents = s.scalars(select(CallDocument).where(CallDocument.call_id == call.id)).all()
        assert sorted(d.is_primary for d in documents) == [False, True]


def test_a_quote_not_in_the_document_writes_no_call_and_is_not_asked_twice(sessions, store, site):
    reply = json.loads(cassette("av-measure-819"))
    reply["criteria"][0]["quote"] = "Право на учество имаат само приватни работодавачи"
    provider = ScriptedProvider(json.dumps(reply))

    first = run(sessions, store, site, provider)
    second = run(sessions, store, site, provider)

    assert outcomes(first) == [pipeline.REVIEW] and outcomes(second) == [pipeline.WAITING]
    assert calls(sessions) == [] and len(provider.requests) == 1
    [item] = items(sessions)
    assert item.payload["stage"] == "extract" and item.payload["public_url"] == PUBLIC_URL


def test_output_invalid_twice_goes_to_review_and_waits_there(sessions, store, site):
    provider = ScriptedProvider('{"document_kind": "call"}', '{"document_kind": "call"}')

    first = run(sessions, store, site, provider)
    second = run(sessions, store, site, provider)

    assert outcomes(first) == [pipeline.REVIEW] and outcomes(second) == [pipeline.WAITING]
    assert calls(sessions) == [] and len(provider.requests) == 2
    [item] = items(sessions)
    assert item.payload["snapshot_ids"] == [first.processed[0].found.snapshot_ids[0]]
    assert "failed validation twice" in item.reason


def test_a_provider_outage_is_retried_on_the_next_run(sessions, store, site):
    first = run(sessions, store, site, FailingProvider())

    assert outcomes(first) == [pipeline.ERROR] and not first.ok and first.run.ok
    assert calls(sessions) == [] and items(sessions) == []
    with sessions() as s:
        ingestion_run = s.get(IngestionRun, first.run.run_id)
        assert not ingestion_run.ok and "provider unreachable" in ingestion_run.error
        assert s.get(SourceHealth, ingestion_run.source_feed_id).consecutive_failures == 0

    second = run(sessions, store, site, ScriptedProvider(cassette("av-measure-819")))
    assert outcomes(second) == [pipeline.CREATED] and second.ok


def test_a_document_the_model_calls_not_a_funding_call_is_reviewed_not_dropped(
    sessions, store, site
):
    reply = json.dumps({"document_kind": "not_a_funding_call", "title_mk": None, "criteria": []})

    result = run(sessions, store, site, ScriptedProvider(reply))

    assert outcomes(result) == [pipeline.REVIEW] and calls(sessions) == []
    [item] = items(sessions)
    assert item.payload["stage"] == "not_a_call"


def test_an_unreadable_document_is_reviewed_and_not_retried(sessions, store, site):
    site.details[819] = b'{"d": ""}'
    provider = ScriptedProvider()

    first = run(sessions, store, site, provider)
    second = run(sessions, store, site, provider)

    assert outcomes(first) == [pipeline.REVIEW] and outcomes(second) == [pipeline.WAITING]
    assert provider.requests == []
    [item] = items(sessions)
    assert item.payload["stage"] == "normalise" and "empty" in item.payload["reasons"][0]


def test_a_call_no_longer_listed_is_closed_without_asking_the_model(sessions, store, site):
    provider = ScriptedProvider(cassette("av-measure-819"))
    run(sessions, store, site, provider)

    site.set_open()  # archived at the source, e.g. the quota filled before the deadline
    result = run(sessions, store, site, provider)

    assert result.processed == [] and result.closed == 1
    [call] = calls(sessions)
    assert call.status == CallStatus.CLOSED and len(provider.requests) == 1


def test_a_listed_call_past_its_deadline_is_closed(sessions, store, site):
    provider = ScriptedProvider(cassette("av-measure-819"))
    run(sessions, store, site, provider)

    run(sessions, store, site, provider, now=dt.datetime(2026, 8, 22, tzinfo=dt.UTC))

    [call] = calls(sessions)
    assert call.status == CallStatus.CLOSED


def test_a_source_is_due_daily_and_again_after_any_failure(sessions, store, site):
    def due(now):
        with sessions() as s:
            return "av" in pipeline.due_sources(s, now)

    with sessions() as s:
        s.execute(delete(IngestionRun))
        s.commit()
    assert due(BEFORE_DEADLINE)  # never run

    failed = run(sessions, store, site, FailingProvider())
    with sessions() as s:
        started = s.get(IngestionRun, failed.run.run_id).started_at
    # The fetch was fine but extraction failed: due at the next wake-up, not tomorrow.
    assert due(started + dt.timedelta(hours=4))

    run(sessions, store, site, ScriptedProvider(cassette("av-measure-819")))
    with sessions() as s:
        started = s.scalars(
            select(IngestionRun.started_at).order_by(IngestionRun.id.desc())
        ).first()
    assert not due(started + dt.timedelta(hours=4))
    assert due(started + dt.timedelta(hours=21))
