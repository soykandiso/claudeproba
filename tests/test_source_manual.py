"""Manual entry by URL (roadmap P1 s16): paste a URL → snapshot → extraction → review.

Acceptance: the same citation quality as a crawled call. The document is the
Economy ministry's call DOCX from reconnaissance, served from a mock site, and the
model's reply is the hand-written tests/cassettes/extract_call/economy-call-3.json.
"""

import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app import create_app
from app.ai.gateway import Gateway
from app.config import load_settings
from app.ingestion.http import PoliteClient
from app.ingestion.snapshots import SnapshotStore
from app.ingestion.source_config import load_sources, sync_sources
from app.ingestion.sources import fetchers, manual
from app.models import (
    Call,
    EligibilityCriterion,
    ModelCall,
    ModelCallPayload,
    Programme,
    RawSnapshot,
    ReviewQueueItem,
    SourceFeed,
)
from app.review import extraction as review
from tests.test_extract import ScriptedProvider
from tests.test_extract_schema import cassette
from tests.test_gateway import DATABASE_AVAILABLE
from tests.test_pipeline import FailingProvider

settings = load_settings()
DOCX = Path(__file__).parent / "fixtures" / "economy" / "call-3-javen-povik.docx"
CALL_URL = "https://portal.gov.example/files/javen-povik.docx"
INSTITUTION = "Министерство за економија и труд"


# -- the URLs (no database) ----------------------------------------------------------------


def test_urls_are_one_per_line_deduplicated_and_in_order():
    assert manual.parse_urls(f" {CALL_URL}\n\nhttps://b.example/prilog.pdf\n{CALL_URL}\n") == [
        CALL_URL,
        "https://b.example/prilog.pdf",
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "барем една"),
        ("\n".join(f"https://a.example/{i}" for i in range(6)), "Најмногу 5"),
        ("ftp://a.example/call.pdf", "Не е веб-адреса"),
        ("javascript:alert(1)", "Не е веб-адреса"),
        ("http://localhost:8000/admin", "внатрешна мрежа"),
        ("http://postgres:5432/", "внатрешна мрежа"),
        ("http://169.254.169.254/latest/meta-data/", "внатрешна мрежа"),
        ("http://10.0.0.5/call", "внатрешна мрежа"),
        ("http://[::1]/call", "внатрешна мрежа"),
    ],
)
def test_what_must_not_be_fetched_is_refused_before_anything_runs(text, message):
    with pytest.raises(manual.InvalidEntry, match=message):
        manual.parse_urls(text)


def test_manual_is_not_a_scheduled_fetcher():
    entry = next(s for s in load_sources() if s.slug == "manual")
    assert entry.access_method == "manual" and not entry.active
    assert "manual" not in fetchers()


# -- the pipeline --------------------------------------------------------------------------

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
        source = s.scalars(select(SourceFeed).where(SourceFeed.slug == "manual")).one()
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


class Site:
    def __init__(self):
        self.robots = "User-agent: *\nAllow: /\n"
        self.status = 200
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=self.robots)
        if str(request.url) == CALL_URL and self.status == 200:
            return httpx.Response(
                200,
                content=DOCX.read_bytes(),
                headers={
                    "content-type": "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                },
            )
        return httpx.Response(self.status if self.status != 200 else 404)


def enter(sessions, tmp_path, site, provider, urls=(CALL_URL,)):
    client = PoliteClient(
        "grantbot/test", min_interval_s=0, transport=httpx.MockTransport(site.handler)
    )
    return manual.run_entry(
        list(urls),
        institution=INSTITUTION,
        note="од весник",
        settings=settings,
        sessions=sessions,
        store=SnapshotStore(tmp_path),
        gateway=lambda: Gateway(sessions, provider),
        client=client,
    )


@needs_database
def test_a_pasted_url_becomes_an_unpublished_cited_call_waiting_for_review(sessions, tmp_path):
    site = Site()

    result = enter(sessions, tmp_path, site, ScriptedProvider(cassette("economy-call-3")))

    assert result.outcome == "created"
    assert site.requests[0].endswith("/robots.txt")  # obeyed like any crawl
    with sessions() as s:
        item = s.get(ReviewQueueItem, result.review_item_id)
        call = s.get(Call, item.call_id)
        assert review.stage_of(item) == review.APPROVE_CALL and not call.is_published
        assert call.canonical_url == CALL_URL
        assert s.get(Programme, call.programme_id).institution == INSTITUTION
        assert s.get(SourceFeed, call.source_feed_id).slug == "manual"
        assert item.payload["listing"]["note"] == "од весник"

        criteria = s.scalars(
            select(EligibilityCriterion).where(EligibilityCriterion.call_id == call.id)
        ).all()
        assert criteria
        for criterion in criteria:
            text = s.get(RawSnapshot, criterion.snapshot_id).normalised_text
            assert text[criterion.quote_start : criterion.quote_end] == criterion.source_quote
        assert review.approval_problems(s, item) == []


@needs_database
@pytest.mark.parametrize(
    ("breakage", "detail"),
    [("gone", "returned HTTP 404"), ("robots", "robots.txt disallows")],
)
def test_a_url_that_cannot_be_fetched_answers_in_the_queue(sessions, tmp_path, breakage, detail):
    site = Site()
    if breakage == "gone":
        site.status = 404
    else:
        site.robots = "User-agent: *\nDisallow: /files/\n"

    result = enter(sessions, tmp_path, site, ScriptedProvider())

    assert result.outcome == manual.FETCH_FAILED
    with sessions() as s:
        item = s.get(ReviewQueueItem, result.review_item_id)
        assert review.stage_of(item) == review.MANUAL_ENTRY
        assert detail in item.payload["detail"] and item.payload["urls"] == [CALL_URL]
        assert item.call_id is None
        assert review.approval_problems(s, item) == [
            "Оваа ставка нема повик за објавување; може само да се затвори."
        ]


@needs_database
def test_a_provider_outage_answers_in_the_queue_and_the_same_urls_can_be_entered_again(
    sessions, tmp_path
):
    site = Site()
    failed = enter(sessions, tmp_path, site, FailingProvider())
    assert failed.outcome == manual.PROCESSING_FAILED
    with sessions() as s:
        assert (
            "provider unreachable"
            in s.get(ReviewQueueItem, failed.review_item_id).payload["detail"]
        )

    again = enter(sessions, tmp_path, site, ScriptedProvider(cassette("economy-call-3")))
    assert again.outcome == "created"


@needs_database
def test_entering_known_documents_again_says_so_and_asks_nothing(sessions, tmp_path):
    site = Site()
    first = enter(sessions, tmp_path, site, ScriptedProvider(cassette("economy-call-3")))

    provider = ScriptedProvider()
    second = enter(sessions, tmp_path, site, provider)

    assert second.outcome == manual.ALREADY_KNOWN and provider.requests == []
    with sessions() as s:
        item = s.get(ReviewQueueItem, second.review_item_id)
        assert item.payload["existing_item_id"] == first.review_item_id


# -- the screen ----------------------------------------------------------------------------


@pytest.fixture
def admin():
    return create_app(load_settings(env="testing", secret_key="test")).test_client()


def token(client) -> str:
    page = client.get("/admin/rachen-vnes").get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def test_the_form_queues_the_entry_for_the_worker(admin, monkeypatch):
    queued = []
    monkeypatch.setattr(manual, "enqueue", lambda settings, *args: queued.append(args) or "job-1")

    response = admin.post(
        "/admin/rachen-vnes",
        data={"csrf": token(admin), "urls": f"{CALL_URL}\n", "institution": f" {INSTITUTION} ",
              "note": "од весник"},
    )  # fmt: skip

    assert response.status_code == 302 and response.location.endswith("/admin/")
    assert queued == [([CALL_URL], INSTITUTION, "од весник")]


def test_a_refused_entry_keeps_what_was_typed(admin, monkeypatch):
    monkeypatch.setattr(manual, "enqueue", lambda *a: pytest.fail("must not be queued"))

    response = admin.post(
        "/admin/rachen-vnes",
        data={"csrf": token(admin), "urls": "http://localhost/x", "institution": INSTITUTION},
    )

    html = response.get_data(as_text=True)
    assert response.status_code == 422 and "внатрешна мрежа" in html
    assert "http://localhost/x</textarea>" in html and f'value="{INSTITUTION}"' in html


def test_an_unreachable_queue_is_said_plainly(admin, monkeypatch):
    def down(*args):
        raise ConnectionError("redis down")

    monkeypatch.setattr(manual, "enqueue", down)

    response = admin.post("/admin/rachen-vnes", data={"csrf": token(admin), "urls": CALL_URL})

    assert response.status_code == 503
    assert "Редот за обработка не е достапен" in response.get_data(as_text=True)


def test_the_form_needs_the_csrf_token(admin, monkeypatch):
    monkeypatch.setattr(manual, "enqueue", lambda *a: pytest.fail("must not be queued"))
    assert admin.post("/admin/rachen-vnes", data={"urls": CALL_URL}).status_code == 400


def test_enqueue_hands_the_worker_the_job_with_a_long_timeout(monkeypatch):
    calls = []

    class FakeQueue:
        def __init__(self, name, connection):
            calls.append(("queue", name))

        def enqueue(self, func, *args, **kwargs):
            calls.append(("enqueue", func, args, kwargs["job_timeout"]))
            return type("Job", (), {"id": "job-1"})()

    monkeypatch.setattr("rq.Queue", FakeQueue)

    assert manual.enqueue(settings, [CALL_URL], INSTITUTION, "") == "job-1"
    assert calls == [
        ("queue", "ingest"),
        ("enqueue", manual.job, ([CALL_URL], INSTITUTION, ""), manual.JOB_TIMEOUT_S),
    ]
