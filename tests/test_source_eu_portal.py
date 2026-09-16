"""The EU Funding & Tenders fetcher (roadmap P1 s13): parsing, then the pipeline end to end.

The parsing tests use responses captured from the portal. The pipeline tests serve
a mock portal built from those topics, and replay the hand-written reply in
tests/cassettes/extract_call/eu-digital-2026-skills-10-edtech.json.
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
from app.ingestion.normalise import NormaliseError, normalise
from app.ingestion.snapshots import SnapshotStore
from app.ingestion.source_config import load_sources, sync_sources
from app.ingestion.sources import fetchers
from app.ingestion.sources.eu_portal import (
    PUBLIC_URL,
    SCOPE,
    SEARCH_URL,
    TOPIC_URL,
    EuPortalFetcher,
    condition_links,
    in_scope,
    parse_search,
    search_request,
)
from app.models import Call, ModelCall, ModelCallPayload, RawSnapshot, ReviewQueueItem, SourceFeed
from app.models.enums import CallStatus
from tests.test_extract import ScriptedProvider
from tests.test_extract_schema import cassette, fixture_text
from tests.test_gateway import DATABASE_AVAILABLE

FIXTURES = Path(__file__).parent / "fixtures" / "eu_portal"
EDTECH = "DIGITAL-2026-SKILLS-10-EDTECH"
COSME = "SMP-COSME-2024-CLUSTER-01"
TODAY = dt.date(2026, 9, 16)

settings = load_settings()


def topic_bytes(identifier: str) -> bytes:
    return (FIXTURES / f"topic-{identifier.lower()}.json").read_bytes()


# -- parsing ------------------------------------------------------------------------------


def test_the_fetcher_is_registered_and_sees_the_whole_listing():
    assert fetchers()["eu-portal"] is EuPortalFetcher and EuPortalFetcher.listing_is_complete


def test_topics_the_portal_still_calls_open_but_whose_deadlines_passed_are_skipped():
    # Captured 16.09.2026: 31 EIC results, 23 of them "Open" or "Forthcoming" with 2023 deadlines.
    page = parse_search((FIXTURES / "search-scope-horizon-eic.json").read_bytes())
    assert page.total == len(page.results) == 31

    kept = [r["metadata"]["identifier"][0] for r in in_scope(page.results, TODAY)]

    assert len(kept) == 8 and all(identifier.startswith("HORIZON-EIC-2026-") for identifier in kept)


def test_a_topic_listed_twice_is_kept_once_and_cascade_calls_are_not_topics():
    # search-open-sme.json holds cascade-funding calls (type 8), one listed twice.
    page = parse_search((FIXTURES / "search-open-sme.json").read_bytes())
    assert in_scope(page.results, TODAY) == []

    as_topics = [{**r, "metadata": {**r["metadata"], "type": ["1"]}} for r in page.results]
    kept = [r["metadata"]["identifier"][0] for r in in_scope(as_topics, dt.date(2026, 1, 1))]
    assert len(kept) == len(set(kept)) == 4


@pytest.mark.parametrize("body", [b"<html>maintenance</html>", b'{"results": []}', b"{}"])
def test_a_broken_search_response_fails_the_crawl(body):
    with pytest.raises(ValueError):
        parse_search(body)


def test_a_search_request_is_the_same_bytes_on_every_run():
    first, again = search_request(SCOPE[0], 2), search_request(SCOPE[0], 2)
    assert first.body == again.body and first.identity == again.identity
    assert first.url.endswith("pageSize=100&pageNumber=2")
    assert b'"frameworkProgramme":["43152860"' in first.body
    assert first.identity != search_request(SCOPE[1], 2).identity


def test_unwrap_renders_the_topic_with_dates_as_dd_mm_yyyy():
    content, content_type = EuPortalFetcher().unwrap(topic_bytes(EDTECH), "application/json")
    text = normalise(content, content_type).text

    assert text == fixture_text("eu-digital-2026-skills-10-edtech")
    lines = text.splitlines()
    assert lines[0] == "EdTech Accelerator"
    assert "Deadline date: 01.10.2026" in lines and "Opening date: 21.04.2026" in lines
    assert "2. Eligible countries" in lines


@pytest.mark.parametrize("body", [b"{}", b'{"TopicDetails": {"identifier": "X"}}', b"not json"])
def test_an_unexpected_topic_is_a_normalise_error(body):
    with pytest.raises(NormaliseError):
        EuPortalFetcher().unwrap(body, "application/json")


def test_the_documents_the_conditions_point_to_are_kept_for_the_reviewer():
    topic = json.loads(topic_bytes(EDTECH))["TopicDetails"]
    links = condition_links(topic)
    assert links[0] == (
        "https://ec.europa.eu/info/funding-tenders/opportunities/docs/2021-2027/digital/"
        "wp-call/2026/call-fiche_digital-2026-skills-10_en.pdf"
    )
    assert len(links) == len(set(links)) and all(link.startswith("http") for link in links)


def test_call_news_and_response_times_are_not_a_change_but_the_topic_text_is():
    fetcher = EuPortalFetcher()
    original = json.loads(topic_bytes(EDTECH))
    news = json.loads(topic_bytes(EDTECH))
    news["TopicDetails"]["latestInfos"].append({"content": "<p>Submission session open.</p>"})
    edited = json.loads(topic_bytes(EDTECH))
    edited["TopicDetails"]["conditions"] += "<p>Corrigendum.</p>"

    def significant(data):
        return fetcher.significant(json.dumps(data).encode())

    assert significant(news) == significant(original)
    assert significant(edited) != significant(original)

    page = json.loads((FIXTURES / "search-scope-horizon-eic.json").read_bytes())
    slower = {**page, "responseTime": 999}
    assert significant(slower) == significant(page)


# -- the pipeline end to end --------------------------------------------------------------


def result(identifier: str, deadline: str, type_: str = "1") -> dict:
    return {
        "metadata": {
            "identifier": [identifier],
            "type": [type_],
            "status": ["31094502"],
            "deadlineDate": [deadline],
        }
    }


class EuPortal:
    """The portal: EdTech open in both scopes, COSME past its deadline but still 'Open'."""

    def __init__(self):
        self.pages = {
            "frameworkProgramme": [
                result(EDTECH, "2026-10-01T00:00:00.000+0000"),
                result(COSME, "2025-02-05T00:00:00.000+0000"),
            ],
            "programmeDivision": [result(EDTECH, "2026-10-01T00:00:00.000+0000")],
        }
        self.topics = {EDTECH: topic_bytes(EDTECH), COSME: topic_bytes(COSME)}
        self.extra_total = 0
        self.response_time = 50

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if str(request.url).startswith(SEARCH_URL):
            field = next(name for name in self.pages if f'"{name}"'.encode() in request.content)
            results = self.pages[field] if request.url.params["pageNumber"] == "1" else []
            self.response_time += 1
            return httpx.Response(
                200,
                json={
                    "totalResults": len(self.pages[field]) + self.extra_total,
                    "responseTime": self.response_time,
                    "results": results,
                },
            )
        for identifier, content in self.topics.items():
            if str(request.url) == TOPIC_URL.format(identifier.lower()):
                return httpx.Response(
                    200, content=content, headers={"content-type": "application/json"}
                )
        return httpx.Response(404)


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
        source = s.scalars(select(SourceFeed).where(SourceFeed.slug == "eu-portal")).one()
        source.is_active = True
        # A cached model reply for the same documents would replace the scripted one.
        s.execute(delete(ModelCallPayload))
        s.execute(delete(ModelCall))
        s.execute(delete(ReviewQueueItem))
        s.execute(delete(Call).where(Call.source_feed_id == source.id))
        s.execute(delete(RawSnapshot).where(RawSnapshot.source_feed_id == source.id))
        s.commit()
    yield factory
    transaction.rollback()
    connection.close()
    engine.dispose()


def run(sessions, store, portal, provider, today=TODAY):
    client = PoliteClient(
        "grantbot/test", min_interval_s=0, transport=httpx.MockTransport(portal.handler)
    )
    return pipeline.run_source(
        EuPortalFetcher(today=lambda: today),
        settings=settings,
        sessions=sessions,
        store=store,
        gateway=lambda: Gateway(sessions, provider),
        client=client,
        now=lambda: dt.datetime.combine(today, dt.time(9), tzinfo=dt.UTC),
    )


def eu_calls(sessions):
    with sessions() as s:
        return s.scalars(select(Call).join(SourceFeed).where(SourceFeed.slug == "eu-portal")).all()


@needs_database
def test_an_open_topic_becomes_an_unpublished_cited_call(sessions, tmp_path):
    portal, provider = EuPortal(), ScriptedProvider(cassette("eu-digital-2026-skills-10-edtech"))

    outcome = run(sessions, SnapshotStore(tmp_path), portal, provider)

    assert outcome.ok and [p.outcome for p in outcome.processed] == [pipeline.CREATED]
    assert len(provider.requests) == 1  # listed in both scopes, extracted once; COSME skipped
    [call] = eu_calls(sessions)
    assert call.title_mk == "EdTech Accelerator" and not call.is_published
    assert call.reference_code == EDTECH and call.status == CallStatus.OPEN
    assert call.canonical_url == PUBLIC_URL.format(EDTECH)
    assert call.deadline_at == dt.datetime(2026, 10, 1, 21, 59, 59, tzinfo=dt.UTC)

    with sessions() as s:
        snapshot = s.get(RawSnapshot, call.primary_snapshot_id)
        assert snapshot.url == TOPIC_URL.format(EDTECH.lower())
        [item] = s.scalars(select(ReviewQueueItem)).all()
    assert item.payload["listing"]["condition_links"].startswith(
        "https://ec.europa.eu/info/funding-tenders/opportunities/docs/2021-2027/digital/"
    )
    for path, citation in item.payload["citations"].items():
        start, end = citation["char_start"], citation["char_end"]
        assert snapshot.normalised_text[start:end] == citation["source_quote"], path


@needs_database
def test_call_news_on_the_next_run_spends_nothing(sessions, tmp_path):
    store = SnapshotStore(tmp_path)
    portal, provider = EuPortal(), ScriptedProvider(cassette("eu-digital-2026-skills-10-edtech"))
    run(sessions, store, portal, provider)

    topic = json.loads(portal.topics[EDTECH])
    topic["TopicDetails"]["latestInfos"].insert(0, {"content": "<p>Session open.</p>"})
    portal.topics[EDTECH] = json.dumps(topic).encode()
    outcome = run(sessions, store, portal, provider)

    assert [p.outcome for p in outcome.processed] == [pipeline.UNCHANGED]
    assert outcome.run.changed == [] and len(provider.requests) == 1


@needs_database
def test_a_topic_whose_deadline_passed_is_closed_even_if_the_portal_says_open(sessions, tmp_path):
    store = SnapshotStore(tmp_path)
    portal, provider = EuPortal(), ScriptedProvider(cassette("eu-digital-2026-skills-10-edtech"))
    run(sessions, store, portal, provider)

    outcome = run(sessions, store, portal, provider, today=dt.date(2026, 10, 2))

    assert outcome.ok and outcome.processed == [] and outcome.closed == 1
    [call] = eu_calls(sessions)
    assert call.status == CallStatus.CLOSED


@needs_database
@pytest.mark.parametrize("breakage", ["incomplete", "empty"])
def test_a_listing_that_does_not_add_up_closes_nothing(sessions, tmp_path, breakage):
    store = SnapshotStore(tmp_path)
    portal, provider = EuPortal(), ScriptedProvider(cassette("eu-digital-2026-skills-10-edtech"))
    run(sessions, store, portal, provider)

    if breakage == "incomplete":
        portal.extra_total = 150  # the portal claims more results than it served
    else:
        portal.pages = {field: [] for field in portal.pages}
    outcome = run(sessions, store, portal, provider)

    assert not outcome.ok and outcome.closed == 0 and outcome.processed == []
    [call] = eu_calls(sessions)
    assert call.status == CallStatus.OPEN
