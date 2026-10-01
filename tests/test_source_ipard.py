"""The IPARD fetcher (roadmap P1 s20): calls in the registry, tables routed to a human.

The programme page and call pages are the reconnaissance captures. Call 03/2025 has
only its advance notice, a PDF with a text layer, extracted with the hand-written
reply tests/cassettes/extract_call/ipard-notice-03-2025.json; call 01/2025 has a
ranking and is out of scope.
"""

import json
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
from selectolax.lexbor import LexborHTMLParser
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.ai.gateway import Gateway
from app.config import load_settings
from app.ingestion import pipeline
from app.ingestion.http import PoliteClient
from app.ingestion.snapshots import SnapshotStore
from app.ingestion.source_config import load_sources, sync_sources
from app.ingestion.sources import fetchers
from app.ingestion.sources.ipard import (
    PROGRAMME_URL,
    TABLES_NOTE,
    IpardFetcher,
    call_files,
    programme_calls,
)
from app.models import (
    Call,
    CallDocument,
    EligibilityCriterion,
    ModelCall,
    ModelCallPayload,
    RawSnapshot,
    ReviewQueueItem,
    SourceFeed,
)
from app.models.enums import CallStatus
from tests.test_extract import ScriptedProvider
from tests.test_extract_schema import cassette
from tests.test_gateway import DATABASE_AVAILABLE

settings = load_settings()
FIXTURES = Path(__file__).parent / "fixtures" / "ipardpa"
SITE = "https://www.ipardpa.gov.mk"
CALL_34 = f"{SITE}/mk/Home/IpardPovici/34"
CALL_32 = f"{SITE}/mk/Home/IpardPovici/32"
NOTICE_34 = f"{SITE}/Upload/Documents/ПРЕТХОДНА НАЈАВА 03-2025.pdf"


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def with_file(html: str, label: str, href: str) -> str:
    """The call page with one more file listed in its content section."""
    tree = LexborHTMLParser(html)
    section = tree.css_first("section.section.mb-3")
    section.insert_child(LexborHTMLParser(f'<p><a href="{href}">{label}</a></p>').body.child)
    return tree.html


# -- parsing ------------------------------------------------------------------------------


def test_the_fetcher_is_registered_and_reads_the_whole_programme():
    assert fetchers()["ipard"] is IpardFetcher and IpardFetcher.listing_is_complete


def test_the_programme_page_lists_every_call_once_newest_first():
    urls = programme_calls(page("listing-ipard-2021-2027.html"))
    assert [u.rsplit("/", 1)[-1] for u in urls] == ["34", "33", "32", "31", "30", "9"]

    with pytest.raises(ValueError, match="no calls"):
        programme_calls(
            "<html><body><a href='/mk/Home/JavniPovici/1'>ИПАРД повици</a></body></html>"
        )


def test_a_call_page_says_which_stage_the_call_is_in():
    announced = call_files(page("call-34.html"), CALL_34)
    assert announced.title == "ЈАВЕН ПОВИК бр.03/2025, Мерка 7"
    assert not announced.decided
    assert [unquote(url) for _, url in announced.documents()] == [NOTICE_34]

    decided = call_files(page("call-32.html"), CALL_32)
    assert decided.decided and len(decided.files) == 10
    # Once published, the call versions are the documents, not the earlier notice.
    assert [label for label, _ in decided.documents()] == [
        "Јавен Повик 01_2025 Кратка верзија",
        "Јавен Повик 01_2025 Долга верзија",
    ]

    with pytest.raises(ValueError, match="content section"):
        call_files("<html><body><h1>Нов изглед</h1></body></html>", CALL_34)


def test_only_the_content_section_of_a_call_page_is_normalised():
    fetcher = IpardFetcher()
    assert fetcher.html_root(CALL_34) == "section.section.mb-3"
    assert fetcher.html_root(NOTICE_34) is None


def test_the_anti_forgery_token_is_not_a_change():
    original = page("call-34.html").encode()
    fresh = original.replace(
        b'__RequestVerificationToken" type="hidden" value="',
        b'__RequestVerificationToken" type="hidden" value="new',
        1,
    )
    assert fresh != original
    assert IpardFetcher().significant(fresh) == IpardFetcher().significant(original)


# -- the pipeline end to end --------------------------------------------------------------


class Agency:
    """ipardpa.gov.mk with two calls: 03/2025 announced, 01/2025 decided."""

    def __init__(self):
        tree = LexborHTMLParser(page("listing-ipard-2021-2027.html"))
        for link in tree.css("a[href]"):
            href = link.attributes["href"]
            if "/IpardPovici/" in href and not href.endswith(("/34", "/32")):
                link.decompose()
        self.programme = tree.html
        self.pages = {CALL_34: page("call-34.html"), CALL_32: page("call-32.html")}
        self.files = {NOTICE_34: (FIXTURES / "call-34-najava-03-2025.pdf").read_bytes()}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = unquote(str(request.url))
        self.requests.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if url == PROGRAMME_URL:
            return httpx.Response(200, text=self.programme, headers={"content-type": "text/html"})
        if url in self.pages:
            return httpx.Response(200, text=self.pages[url], headers={"content-type": "text/html"})
        if url in self.files:
            return httpx.Response(
                200, content=self.files[url], headers={"content-type": "application/pdf"}
            )
        return httpx.Response(404)


def notice_reply() -> str:
    """The hand-written reply, its quotes pointing at the notice: document 2 after the page."""
    reply = json.loads(cassette("ipard-notice-03-2025"))
    for value in reply.values():
        if isinstance(value, dict) and "document" in value:
            value["document"] = 2
    for criterion in reply["criteria"]:
        criterion["document"] = 2
    return json.dumps(reply, ensure_ascii=False)


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
        source = s.scalars(select(SourceFeed).where(SourceFeed.slug == "ipard")).one()
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


def run(sessions, tmp_path, agency, provider):
    client = PoliteClient(
        "grantbot/test", min_interval_s=0, transport=httpx.MockTransport(agency.handler)
    )
    return pipeline.run_source(
        IpardFetcher(),
        settings=settings,
        sessions=sessions,
        store=SnapshotStore(tmp_path),
        gateway=lambda: Gateway(sessions, provider),
        client=client,
    )


def ipard_calls(s):
    return s.scalars(select(Call).join(SourceFeed).where(SourceFeed.slug == "ipard")).all()


@needs_database
def test_an_announced_call_is_in_the_registry_with_a_note_to_check_the_tables(sessions, tmp_path):
    agency = Agency()

    result = run(sessions, tmp_path, agency, ScriptedProvider(notice_reply()))

    assert result.ok and [p.outcome for p in result.processed] == [pipeline.CREATED]
    assert not any("01_2025" in url or "РАНГ" in url for url in agency.requests)  # decided call
    with sessions() as s:
        [call] = ipard_calls(s)
        assert call.canonical_url == CALL_34 and call.status == CallStatus.ANNOUNCED
        assert s.get(RawSnapshot, call.primary_snapshot_id).url == CALL_34
        documents = s.scalars(select(CallDocument).where(CallDocument.call_id == call.id)).all()
        assert len(documents) == 2
        page_text = s.get(RawSnapshot, call.primary_snapshot_id).normalised_text
        assert page_text.startswith("ЈАВЕН ПОВИК бр.03/2025, Мерка 7") and "За нас" not in page_text

        [item] = s.scalars(select(ReviewQueueItem)).all()
        assert item.payload["listing"]["note"] == TABLES_NOTE
        assert item.payload["listing"]["stage"] == "advance notice only"
        for criterion in s.scalars(
            select(EligibilityCriterion).where(EligibilityCriterion.call_id == call.id)
        ):
            text = s.get(RawSnapshot, criterion.snapshot_id).normalised_text
            assert text[criterion.quote_start : criterion.quote_end] == criterion.source_quote


@needs_database
def test_publishing_the_call_updates_the_announced_call_instead_of_adding_one(sessions, tmp_path):
    agency = Agency()
    run(sessions, tmp_path, agency, ScriptedProvider(notice_reply()))

    short = f"{SITE}/Upload/Documents/Јавен Повик 03_2025 Кратка верзија.pdf"
    agency.pages[CALL_34] = with_file(
        agency.pages[CALL_34], "Јавен Повик 03_2025 Кратка верзија", short
    )
    agency.files[short] = agency.files[
        NOTICE_34
    ]  # the text does not matter here, the identity does
    reply = json.loads(notice_reply())
    published = run(
        sessions, tmp_path, agency, ScriptedProvider(json.dumps(reply, ensure_ascii=False))
    )

    assert [p.outcome for p in published.processed] == [pipeline.UPDATED]
    with sessions() as s:
        [call] = ipard_calls(s)
        assert call.canonical_url == CALL_34


@needs_database
def test_a_ranking_on_the_page_takes_the_call_out_of_scope_and_closes_it(sessions, tmp_path):
    agency = Agency()
    provider = ScriptedProvider(notice_reply())
    run(sessions, tmp_path, agency, provider)

    agency.pages[CALL_34] = with_file(
        agency.pages[CALL_34],
        "РАНГ ЛИСТА НА СООДВЕТНИ БАРАЊА ЗА МЕРКА 7",
        "/Upload/Documents/rang.pdf",
    )
    decided = run(sessions, tmp_path, agency, provider)

    assert decided.ok and decided.processed == [] and decided.closed == 1
    assert len(provider.requests) == 1
    with sessions() as s:
        [call] = ipard_calls(s)
        assert call.status == CallStatus.CLOSED
