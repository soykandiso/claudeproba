"""The Economy ministry fetcher (roadmap P1 s18): calls in the registry, news not ingested.

Parsing runs over the pages captured in reconnaissance and the empty listing
captured on 16.09.2026. The pipeline test serves the ministry from those pages:
call 3's page and its DOCX call text, extracted with the hand-written reply in
tests/cassettes/extract_call/economy-call-3.json.
"""

import datetime as dt
import re
from pathlib import Path

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
from app.ingestion.sources.economy import (
    LISTING_URL,
    EconomyFetcher,
    call_page,
    listing_rows,
    without_livewire_state,
)
from app.models import Call, ModelCall, ModelCallPayload, RawSnapshot, ReviewQueueItem, SourceFeed
from app.models.enums import CallStatus
from tests.test_extract import ScriptedProvider
from tests.test_extract_schema import cassette
from tests.test_gateway import DATABASE_AVAILABLE

settings = load_settings()
FIXTURES = Path(__file__).parent / "fixtures" / "economy"
CALL_3 = (
    f"{LISTING_URL}/javen-povik-za-finansiska-poddrska-na-mikro-mali-i-sredni-pretprijatija-"
    "i-zanaetcii"
)
CALL_3_TEXT = (
    "https://portal.mdt.gov.mk/post-body-files/javen-povik-za-finansiska-poddrska-na-mikro-mali-"
    "i-sredni-pretprijatija-i-zanaetcii-file-tw5n.docx"
)


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# -- parsing ------------------------------------------------------------------------------


def test_the_fetcher_is_registered_and_its_listing_is_complete():
    assert fetchers()["economy"] is EconomyFetcher and EconomyFetcher.listing_is_complete


def test_the_listing_gives_each_open_call_once_and_nothing_from_the_menu():
    rows = listing_rows(page("listing-javni-oglasi.html"))

    assert [r.deadline for r in rows] == ["15.09.2026", "15.09.2026"]
    assert all(r.institution == "Министерство за економија и труд" for r in rows)
    assert rows[1].title.startswith("ЈАВЕН ПОВИК За зајакнување на соработката")
    assert all("/javni-objavi/javni-oglasi/" in r.url for r in rows)

    closed = listing_rows(page("listing-zavrseni.html"))
    urls = " ".join(r.url for r in closed)
    assert len(closed) == 20
    # The menu links to the closed listings and to competitions; neither is a call row.
    assert "zavrseni-javni-oglasi" not in urls and "odnosi-so-javnost" not in urls


def test_no_calls_with_the_sites_own_message_is_an_empty_source_without_it_a_broken_page():
    assert listing_rows(page("listing-javni-oglasi-empty.html")) == []

    redesigned = page("listing-javni-oglasi-empty.html").replace(
        "Во моментот нема активни јавни огласи", "Страницата е во изработка"
    )
    with pytest.raises(ValueError, match="no calls"):
        listing_rows(redesigned)


def test_a_full_page_fails_rather_than_missing_page_two():
    rows = "".join(
        f'<div><a href="{LISTING_URL}/call-{i}">Јавен повик {i}</a><span>01/10/2026</span></div>'
        for i in range(25)
    )
    with pytest.raises(ValueError, match="second page"):
        listing_rows(f"<html><body>{rows}</body></html>")


def test_a_call_page_names_its_call_text_and_keeps_the_forms_for_the_reviewer():
    call = call_page(page("call-3.html"), CALL_3)

    assert call.call_text_url == CALL_3_TEXT
    assert call.deadline == "30.06.2026"
    assert call.institution == "Министерството за економија и труд"
    assert [label for label, _ in call.attachments] == [
        "Јавен повик",
        "Барање",
        "Образец изјава - Државна помош",
        "Образец изјава",
    ]
    # Numbers split across spans are joined as they render (docs/sources.md §6.3).
    labels = [label for label, _ in call_page(page("call-1.html"), CALL_3).attachments]
    assert "Образец „Изјава – Државна помош 2026“" in labels

    without = page("call-3.html").replace("Јавен повик &gt;&gt;&gt;", "Текст &gt;&gt;&gt;")
    without = re.sub(r">\s*Јавен повик\s*(&gt;|>){3}", ">Текст >>>", without)
    assert call_page(without, CALL_3).call_text_url is None


def test_livewire_tokens_are_not_a_change_but_the_calls_are():
    original = page("listing-javni-oglasi.html").encode()
    fresh = re.sub(rb'wire:id="[^"]*"', b'wire:id="zzzzzzzzzzzzzzzzzzzz"', original)
    fresh = re.sub(rb'content="[A-Za-z0-9]{40}"', b'content="' + b"x" * 40 + b'"', fresh)
    assert fresh != original
    assert without_livewire_state(fresh) == without_livewire_state(original)

    edited = original.replace(b"15/09/2026", b"22/09/2026", 1)
    assert without_livewire_state(edited) != without_livewire_state(original)


# -- the pipeline end to end --------------------------------------------------------------


class Ministry:
    """economy.gov.mk and portal.mdt.gov.mk, with call 3 as the one open call."""

    def __init__(self):
        self.listing = self.one_open_call()
        self.requests: list[str] = []

    @staticmethod
    def one_open_call() -> str:
        """The open listing of 13.09.2026, its first row pointing at call 3, the second removed."""
        tree = LexborHTMLParser(page("listing-javni-oglasi.html"))
        links = [
            a for a in tree.css("a[href]") if "/javni-objavi/javni-oglasi/" in a.attributes["href"]
        ]
        links[0].attrs["href"] = CALL_3
        row = links[1].parent
        while "15/09/2026" not in row.text():
            row = row.parent
        row.decompose()
        return tree.html

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /login\n")
        if url == LISTING_URL:
            # A fresh CSRF token on every request, as the site does.
            html = self.listing.replace(
                'name="csrf-token" content="', f'name="csrf-token" content="{len(self.requests)}'
            )
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        if url == CALL_3:
            return httpx.Response(
                200, text=page("call-3.html"), headers={"content-type": "text/html"}
            )
        if url == CALL_3_TEXT:
            return httpx.Response(
                200,
                content=(FIXTURES / "call-3-javen-povik.docx").read_bytes(),
                headers={"content-type": "application/octet-stream"},
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
        source = s.scalars(select(SourceFeed).where(SourceFeed.slug == "economy")).one()
        source.is_active = True
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


def run(sessions, tmp_path, ministry, provider):
    client = PoliteClient(
        "grantbot/test", min_interval_s=0, transport=httpx.MockTransport(ministry.handler)
    )
    return pipeline.run_source(
        EconomyFetcher(),
        settings=settings,
        sessions=sessions,
        store=SnapshotStore(tmp_path),
        gateway=lambda: Gateway(sessions, provider),
        client=client,
        now=lambda: dt.datetime(2026, 6, 20, 9, 0, tzinfo=dt.UTC),
    )


@needs_database
def test_an_open_call_is_in_the_registry_from_its_call_text_with_citations(sessions, tmp_path):
    ministry = Ministry()

    result = run(sessions, tmp_path, ministry, ScriptedProvider(cassette("economy-call-3")))

    assert result.ok and [p.outcome for p in result.processed] == [pipeline.CREATED]
    # The forms were not fetched: templates, and legacy .doc the normaliser refuses.
    assert not any(url.endswith(".doc") for url in ministry.requests)
    with sessions() as s:
        [call] = s.scalars(select(Call).join(SourceFeed).where(SourceFeed.slug == "economy")).all()
        assert call.canonical_url == CALL_3 and not call.is_published
        assert s.get(RawSnapshot, call.primary_snapshot_id).url == CALL_3_TEXT
        [item] = s.scalars(select(ReviewQueueItem)).all()
        assert "Барање: https://portal.mdt.gov.mk/" in item.payload["listing"]["attachments"]
        assert item.payload["listing"]["page_deadline"] == "30.06.2026"
        for path, citation in item.payload["citations"].items():
            text = s.get(RawSnapshot, citation["snapshot_id"]).normalised_text
            assert (
                text[citation["char_start"] : citation["char_end"]] == citation["source_quote"]
            ), path


@needs_database
def test_a_new_csrf_token_changes_nothing_and_an_emptied_listing_closes_the_call(
    sessions, tmp_path
):
    ministry = Ministry()
    provider = ScriptedProvider(cassette("economy-call-3"))
    run(sessions, tmp_path, ministry, provider)

    again = run(sessions, tmp_path, ministry, provider)
    assert again.run.changed == [] and [p.outcome for p in again.processed] == [pipeline.UNCHANGED]

    ministry.listing = page("listing-javni-oglasi-empty.html")
    emptied = run(sessions, tmp_path, ministry, provider)

    assert emptied.ok and emptied.processed == [] and emptied.closed == 1
    assert len(provider.requests) == 1
    with sessions() as s:
        [call] = s.scalars(select(Call).join(SourceFeed).where(SourceFeed.slug == "economy")).all()
        assert call.status == CallStatus.CLOSED


@needs_database
def test_a_redesigned_listing_fails_the_run_and_closes_nothing(sessions, tmp_path):
    ministry = Ministry()
    run(sessions, tmp_path, ministry, ScriptedProvider(cassette("economy-call-3")))

    ministry.listing = "<html><body><h1>Јавни огласи</h1><p>Нов изглед</p></body></html>"
    broken = run(sessions, tmp_path, ministry, ScriptedProvider())

    assert not broken.ok and broken.closed == 0 and "no calls" in broken.run.error
    with sessions() as s:
        [call] = s.scalars(select(Call).join(SourceFeed).where(SourceFeed.slug == "economy")).all()
        assert call.status == CallStatus.OPEN
