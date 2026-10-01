"""Municipal listings (roadmap P1 s19): Skopje's calls in the registry, and a second
municipality added by configuration alone.

Skopje's listing is the page captured in reconnaissance; its craft-subsidy call is a
scanned PDF whose OCR output was recorded once (tests/fixtures/skopje/call-12149.ocr.json)
and extracted with the hand-written reply tests/cassettes/extract_call/skopje-call-12149.json.
"""

import datetime as dt
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.ai.gateway import Gateway
from app.config import load_settings
from app.ingestion import pipeline
from app.ingestion.http import PoliteClient, Request, Response
from app.ingestion.snapshots import SnapshotStore
from app.ingestion.source_config import SourceEntry, load_sources, sync_sources
from app.ingestion.sources import fetchers
from app.ingestion.sources.municipal import (
    MunicipalFetcher,
    excluded,
    fetcher_for,
    is_document,
    parse_listing,
)
from app.models import (
    Call,
    EligibilityCriterion,
    ModelCall,
    ModelCallPayload,
    RawSnapshot,
    ReviewQueueItem,
    SourceFeed,
)
from app.models.enums import CallStatus, TextSource
from tests.test_extract import ScriptedProvider
from tests.test_extract_schema import RecordedOcr, cassette
from tests.test_gateway import DATABASE_AVAILABLE

settings = load_settings()
FIXTURES = Path(__file__).parent / "fixtures" / "skopje"
LISTING = (FIXTURES / "listing-javni-povici.html").read_text(encoding="utf-8")
CRAFTS = "https://skopje.gov.mk/media/12149/јавен-повик-субвенции-на-занаети.pdf"
ON_16_SEPTEMBER = dt.date(2026, 9, 16)


def skopje() -> type[MunicipalFetcher]:
    return fetchers()["skopje"]


# -- the listing (no database) -------------------------------------------------------------


def test_skopje_is_a_configured_municipal_listing():
    assert issubclass(skopje(), MunicipalFetcher) and skopje().listing_is_complete
    assert skopje().options.listing_url == "https://skopje.gov.mk/mk/apliciraj/javni-povici/"


def test_the_archive_is_parsed_whole_and_only_open_funding_calls_are_in_scope():
    options = skopje().options
    items = parse_listing(LISTING, options, options.listing_url)
    assert len(items) == 38

    in_scope = [i for i in items if i.open_on(ON_16_SEPTEMBER) and not excluded(i, options)]
    assert [i.url for i in in_scope] == [CRAFTS]

    excluded_items = [i for i in items if excluded(i, options)]
    # The two tenders with RAR/ZIP dossiers, and a call for an expert to evaluate
    # procurements ("…набавки"): not funding either, and closed since 29.03.2026.
    assert sum(i.url.endswith((".rar", ".zip")) for i in excluded_items) == 2
    assert len(excluded_items) == 3
    assert "експерт" in next(i.title for i in excluded_items if i.url.endswith(".pdf"))
    # The youth assembly closed on 14.09.2026: listed, no longer in scope.
    assert any(i.deadline == dt.date(2026, 9, 14) for i in items)


def test_criteria_attachments_are_documents_and_forms_are_not():
    options = skopje().options
    festival = next(
        i
        for i in parse_listing(LISTING, options, options.listing_url)
        if [label for label, _ in i.attachments][:2] == ["Критериуми", "Правилник"]
    )
    assert [is_document(label, options) for label, _ in festival.attachments] == [
        True,
        False,
        False,
        False,
    ]
    assert is_document("Цели и критериуми", options)


def test_a_page_without_any_listing_item_fails():
    options = skopje().options
    with pytest.raises(ValueError, match="no items"):
        parse_listing("<html><body><p>Страницата е преуредена</p></body></html>", options, "")


@pytest.mark.parametrize(
    "broken",
    [
        {"item": None},  # a required selector missing
        {"kind": "something_else"},
        {"listing_url": "skopje.gov.mk/javni-povici"},
        {"typo_selector": "div.x"},  # an unknown key is an error, not ignored
    ],
)
def test_a_wrong_config_block_is_refused_when_the_fetcher_is_built(broken):
    entry = next(s for s in load_sources() if s.slug == "skopje")
    options = {**entry.options, **broken}
    options = {k: v for k, v in options.items() if v is not None}
    with pytest.raises(ValidationError):
        fetcher_for(entry.model_copy(update={"options": options}))


# -- a second municipality, configuration only ---------------------------------------------

BITOLA_LISTING = """
<html><body><ul class="povici">
  <li class="povik">
    <h3><a href="/files/povik-zanaetchii-2026.pdf">Јавен повик за поддршка на занаетчии</a></h3>
    <span class="rok">Рок: 15.10.2026</span>
    <ul class="prilozi">
      <li><a href="/files/kriteriumi-2026.pdf">Критериуми за оценување</a></li>
      <li><a href="/files/barane.docx">Барање</a></li>
    </ul>
  </li>
  <li class="povik">
    <h3><a href="/files/tender.zip">Јавен повик за набавка на возила</a></h3>
    <span class="rok">Рок: 20.10.2026</span>
  </li>
  <li class="povik">
    <h3><a href="/files/stari.pdf">Јавен повик за млади 2025</a></h3>
    <span class="rok">Рок: 01.12.2025</span>
  </li>
</ul></body></html>
"""


class FakeContext:
    """Just what a crawl uses: fetch and found_call. No database."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.fetched: list[str] = []
        self.found: list[tuple[str, list[str], dict]] = []

    def fetch(self, request: Request):
        self.fetched.append(request.url)
        response = Response(
            request, 200, self.pages.get(request.url, "%PDF-").encode(), None, request.url
        )
        return type("Fetched", (), {"response": response})()

    def found_call(self, public_url, documents, listing=None):
        self.found.append((public_url, [d.response.request.url for d in documents], listing))


def test_a_second_municipality_with_a_different_page_is_only_a_config_entry():
    entry = SourceEntry(
        slug="bitola",
        name_mk="Општина Битола",
        name_en="Municipality of Bitola",
        institution="Општина Битола",
        base_url="https://bitola.example.mk",
        access_method="pdf_index",
        expected_cadence_days=30,
        staleness_sla_days=120,
        rate_limit_rps=0.2,
        options={
            "kind": "municipal_listing",
            "listing_url": "https://bitola.example.mk/javni-povici",
            "item": "li.povik",
            "title": "h3 a",
            "deadline": "span.rok",
            "attachments": "ul.prilozi a",
            "document_labels": ["критериуми"],
            "exclude_titles": ["набавка"],
        },
    )
    fetcher = fetcher_for(entry)(today=lambda: ON_16_SEPTEMBER)
    ctx = FakeContext({"https://bitola.example.mk/javni-povici": BITOLA_LISTING})

    fetcher.crawl(ctx)

    assert fetcher.slug == "bitola"
    [(public_url, documents, listing)] = ctx.found
    assert public_url == "https://bitola.example.mk/files/povik-zanaetchii-2026.pdf"
    assert documents == [public_url, "https://bitola.example.mk/files/kriteriumi-2026.pdf"]
    assert listing["open_until"] == "15.10.2026"
    assert "Барање: https://bitola.example.mk/files/barane.docx" in listing["attachments"]
    assert not any(url.endswith((".zip", "stari.pdf", ".docx")) for url in ctx.fetched)


# -- Skopje through the pipeline -----------------------------------------------------------

needs_database = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)


class SkopjeSite:
    def __init__(self):
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = unquote(str(request.url))
        self.requests.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)  # skopje.gov.mk has none: everything allowed
        if url == skopje().options.listing_url:
            return httpx.Response(200, text=LISTING, headers={"content-type": "text/html"})
        if url == CRAFTS:
            return httpx.Response(
                200,
                content=(FIXTURES / "call-12149.pdf").read_bytes(),
                headers={"content-type": "application/pdf"},
            )
        return httpx.Response(404)


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
        source = s.scalars(select(SourceFeed).where(SourceFeed.slug == "skopje")).one()
        # A cached model reply for the same document would replace the scripted one.
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


def run(sessions, tmp_path, site, provider, today=ON_16_SEPTEMBER):
    client = PoliteClient(
        "grantbot/test", min_interval_s=0, transport=httpx.MockTransport(site.handler)
    )
    return pipeline.run_source(
        skopje()(today=lambda: today),
        settings=settings,
        sessions=sessions,
        store=SnapshotStore(tmp_path),
        gateway=lambda: Gateway(sessions, provider),
        client=client,
        ocr=RecordedOcr("skopje/call-12149.ocr.json"),
        now=lambda: dt.datetime.combine(today, dt.time(9), tzinfo=dt.UTC),
    )


@needs_database
def test_the_open_craft_subsidy_call_is_in_the_registry_read_by_ocr_and_cited(sessions, tmp_path):
    site = SkopjeSite()

    result = run(sessions, tmp_path, site, ScriptedProvider(cassette("skopje-call-12149")))

    assert result.ok and [p.outcome for p in result.processed] == [pipeline.CREATED]
    assert not any(url.endswith((".rar", ".zip")) for url in site.requests)  # tenders
    with sessions() as s:
        [call] = s.scalars(select(Call).join(SourceFeed).where(SourceFeed.slug == "skopje")).all()
        assert call.canonical_url == CRAFTS and not call.is_published
        assert call.grant_max_mkd == 20000 and call.total_budget_mkd == 400000
        snapshot = s.get(RawSnapshot, call.primary_snapshot_id)
        assert snapshot.text_source == TextSource.OCR
        criteria = s.scalars(
            select(EligibilityCriterion).where(EligibilityCriterion.call_id == call.id)
        ).all()
        assert len(criteria) == 5
        for criterion in criteria:
            assert (
                snapshot.normalised_text[criterion.quote_start : criterion.quote_end]
                == criterion.source_quote
            )


@needs_database
def test_the_call_closes_when_its_date_passes_although_the_archive_still_lists_it(
    sessions, tmp_path
):
    site = SkopjeSite()
    provider = ScriptedProvider(cassette("skopje-call-12149"))
    run(sessions, tmp_path, site, provider)

    later = run(sessions, tmp_path, site, provider, today=dt.date(2026, 12, 1))

    assert later.ok and later.processed == [] and later.closed == 1
    with sessions() as s:
        [call] = s.scalars(select(Call).join(SourceFeed).where(SourceFeed.slug == "skopje")).all()
        assert call.status == CallStatus.CLOSED
