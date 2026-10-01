"""Normalising stored snapshots against a real PostgreSQL."""

import datetime as dt
import hashlib
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import load_settings
from app.ingestion.normalise import NORMALISER_VERSION
from app.ingestion.normalise.pdf import OcrPage
from app.ingestion.normalise.snapshot import normalise_snapshot, pending_snapshots
from app.ingestion.snapshots import SnapshotStore
from app.models import RawSnapshot, ReviewQueueItem, SourceFeed
from app.models.enums import AccessMethod, TextSource

settings = load_settings()
FIXTURES = Path(__file__).parent / "fixtures"

try:
    with psycopg.connect(settings.database_url, connect_timeout=2):
        DATABASE_AVAILABLE = True
except Exception:
    DATABASE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)


class LowConfidenceOcr:
    def read_pages(self, pdf, page_numbers):
        return {n: OcrPage(f"нејасен текст {n}", 60.0) for n in page_numbers}


@pytest.fixture
def session():
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    with sessionmaker(bind=connection, join_transaction_mode="create_savepoint")() as s:
        yield s
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path)


@pytest.fixture
def add_snapshot(session, store):
    feed = SourceFeed(
        slug="test-normalise", name_mk="Тест", name_en="Test", institution="Test",
        base_url="https://gov.example", access_method=AccessMethod.HTML,
        expected_cadence=dt.timedelta(days=7), staleness_sla=dt.timedelta(days=30),
    )  # fmt: skip
    session.add(feed)
    session.flush()

    def add(content: bytes, content_type: str | None = None) -> RawSnapshot:
        sha = hashlib.sha256(content).hexdigest()
        key = SnapshotStore.key_for(feed.slug, sha)
        store.put(key, content)
        snapshot = RawSnapshot(
            source_feed_id=feed.id, url=f"https://gov.example/{sha[:8]}", content_sha256=sha,
            http_status=200, content_type=content_type, byte_length=len(content), storage_key=key,
        )  # fmt: skip
        session.add(snapshot)
        session.flush()
        return snapshot

    return add


def reviews_for(session, snapshot):
    return [
        item for item in session.query(ReviewQueueItem).all()
        if item.payload.get("snapshot_id") == snapshot.id
    ]  # fmt: skip


def test_a_document_is_normalised_and_recorded(session, store, add_snapshot):
    snapshot = add_snapshot((FIXTURES / "economy/call-3-javen-povik.docx").read_bytes())

    outcome = normalise_snapshot(session, store, snapshot)

    assert outcome.ok and outcome.review_item_id is None
    assert "200.000 денари" in snapshot.normalised_text
    assert snapshot.normaliser_version == NORMALISER_VERSION
    assert snapshot.text_source == TextSource.NATIVE
    assert snapshot.ocr_mean_confidence is None


def test_normalised_text_is_never_rewritten(session, store, add_snapshot):
    """Evidence cites offsets into it; a newer normaliser must not move them."""
    snapshot = add_snapshot(b"<html><body><p>\xd0\xbd\xd0\xbe\xd0\xb2\xd0\xbe</p></body></html>")
    snapshot.normalised_text = "text an earlier normaliser produced"
    snapshot.normaliser_version = "2020-01-01.1"
    session.flush()

    outcome = normalise_snapshot(session, store, snapshot)

    assert outcome.detail == "already normalised"
    assert snapshot.normalised_text == "text an earlier normaliser produced"
    assert snapshot.normaliser_version == "2020-01-01.1"


def test_an_unreadable_document_goes_to_review_and_is_not_retried(session, store, add_snapshot):
    snapshot = add_snapshot(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100)  # legacy .doc

    outcome = normalise_snapshot(session, store, snapshot)

    assert not outcome.ok
    assert snapshot.normalised_text is None
    [item] = reviews_for(session, snapshot)
    assert item.payload["stage"] == "normalise" and "legacy" in item.payload["reasons"][0]
    assert snapshot not in pending_snapshots(session, limit=10_000), "waiting for a human"


def test_doubtful_ocr_keeps_its_text_and_goes_to_review(session, store, add_snapshot):
    snapshot = add_snapshot((FIXTURES / "skopje/call-12094.pdf").read_bytes())

    outcome = normalise_snapshot(session, store, snapshot, ocr=LowConfidenceOcr())

    assert outcome.ok and outcome.review_item_id
    assert snapshot.text_source == TextSource.OCR
    assert float(snapshot.ocr_mean_confidence) == 60.0
    assert "нејасен текст 1" in snapshot.normalised_text
    assert len(reviews_for(session, snapshot)) == 1


def test_pending_means_not_normalised_and_not_waiting_for_review(session, store, add_snapshot):
    waiting = add_snapshot(b"<html><body><p>pending</p></body></html>", "text/html")
    done = add_snapshot((FIXTURES / "economy/call-3-javen-povik.docx").read_bytes())
    normalise_snapshot(session, store, done)

    pending = pending_snapshots(session, limit=10_000)

    assert waiting in pending
    assert done not in pending
