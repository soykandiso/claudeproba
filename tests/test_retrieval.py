"""Chunk indexing and hybrid retrieval against a real PostgreSQL, with a stand-in embedder.

The real model's quality is tested in tests/test_retrieval_paraphrase.py. Here the
vectors come from which topic words a text contains, which is enough to test that
the rankings, their fusion, the scope and the bookkeeping are right.
"""

import datetime as dt
import hashlib

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import load_settings
from app.models import Call, CallDocument, Chunk, Programme, RawSnapshot, SourceFeed
from app.models.enums import AccessMethod
from app.retrieval.index import chunk_snapshot, index_pending
from app.retrieval.search import call_snapshot_ids, hybrid_retrieve
from tests.test_extract_schema import fixture_text
from tests.test_gateway import DATABASE_AVAILABLE

settings = load_settings()

pytestmark = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)


class TopicEmbedder:
    TOPICS = ["машин", "вработен", "рок", "такс", "стечај", "жена"]

    def __init__(self, name: str = "topics@test"):
        self.name = name
        self.passages_embedded = 0

    def passages(self, texts):
        self.passages_embedded += len(texts)
        return [self._vector(text) for text in texts]

    def query(self, text):
        return self._vector(text)

    def _vector(self, text):
        vector = [0.0] * 1024
        vector[-1] = 0.01  # never the zero vector, whose cosine distance is undefined
        for i, topic in enumerate(self.TOPICS):
            vector[i] = float(text.lower().count(topic))
        return vector


@pytest.fixture
def sessions():
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield factory
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def feed(sessions):
    with sessions() as session:
        feed = SourceFeed(
            slug="test-retrieval", name_mk="Тест", name_en="Test", institution="Test",
            base_url="https://gov.example", access_method=AccessMethod.HTML,
            expected_cadence=dt.timedelta(days=7), staleness_sla=dt.timedelta(days=30),
        )  # fmt: skip
        session.add(feed)
        session.commit()
        return feed


@pytest.fixture
def add_snapshot(sessions, feed):
    def add(text: str | None, url: str | None = None, seen: dt.datetime | None = None) -> int:
        sha = hashlib.sha256((text or "").encode() + (url or "").encode()).hexdigest()
        with sessions() as session:
            snapshot = RawSnapshot(
                source_feed_id=feed.id, url=url or f"https://gov.example/{sha[:8]}",
                content_sha256=sha, http_status=200, storage_key=f"test/{sha}",
                normalised_text=text,
            )  # fmt: skip
            if seen:
                snapshot.last_seen_at = seen
            session.add(snapshot)
            session.commit()
            return snapshot.id

    return add


def chunks_of(sessions, snapshot_id):
    with sessions() as session:
        return list(
            session.scalars(
                select(Chunk).where(Chunk.snapshot_id == snapshot_id).order_by(Chunk.ordinal)
            )
        )


def test_indexing_writes_offset_exact_chunks_once_and_embeds_them(sessions, add_snapshot):
    text = fixture_text("economy-call-3")
    snapshot_id = add_snapshot(text)
    blank_id = add_snapshot(" \n\f ")
    unread_id = add_snapshot(None)
    embedder = TopicEmbedder()

    first = index_pending(sessions, embedder)

    chunks = chunks_of(sessions, snapshot_id)
    assert len(chunks) > 5
    assert all(c.text == text[c.char_start : c.char_end] for c in chunks)
    assert all(c.embedding is not None and c.embedding_model == embedder.name for c in chunks)
    assert first.chunks_written >= len(chunks)
    assert chunks_of(sessions, blank_id) == [] and chunks_of(sessions, unread_id) == []

    again = TopicEmbedder()
    second = index_pending(sessions, again)
    assert (second.snapshots_chunked, second.chunks_written, second.chunks_embedded) == (0, 0, 0)
    assert again.passages_embedded == 0, "an unchanged document costs nothing"
    assert [c.id for c in chunks_of(sessions, snapshot_id)] == [c.id for c in chunks]


def test_a_different_embedding_model_re_embeds_and_old_vectors_are_not_compared(
    sessions, add_snapshot
):
    snapshot_id = add_snapshot(fixture_text("av-measure-819"))
    index_pending(sessions, TopicEmbedder("topics@v1"))
    v2 = TopicEmbedder("topics@v2")

    with sessions() as session:
        before = hybrid_retrieve(session, v2, [snapshot_id], "вработено лице")
    assert before.unembedded == len(chunks_of(sessions, snapshot_id))
    assert not before.complete
    assert all(p.vector_rank is None for p in before.passages)

    index_pending(sessions, v2)

    with sessions() as session:
        after = hybrid_retrieve(session, v2, [snapshot_id], "вработено лице")
    assert after.complete
    assert all(c.embedding_model == "topics@v2" for c in chunks_of(sessions, snapshot_id))


def test_trigram_finds_an_exact_code_the_vectors_know_nothing_about(sessions, add_snapshot):
    text = fixture_text("economy-call-3")
    snapshot_id = add_snapshot(text)
    index_pending(sessions, TopicEmbedder())

    with sessions() as session:
        result = hybrid_retrieve(session, TopicEmbedder(), [snapshot_id], "Приходна шифра 722313")

    assert "722313 00" in result.passages[0].text
    (best_trigram,) = [p for p in result.passages if p.trigram_rank == 1]
    assert "722313 00" in best_trigram.text


def test_the_vector_ranking_takes_part_in_the_fusion(sessions, add_snapshot):
    text = fixture_text("economy-call-3")
    snapshot_id = add_snapshot(text)
    index_pending(sessions, TopicEmbedder())

    with sessions() as session:
        result = hybrid_retrieve(session, TopicEmbedder(), [snapshot_id], "стечај?", k=3)

    (best_vector,) = [p for p in result.passages if p.vector_rank == 1]
    assert "стечајна постапка" in best_vector.text
    assert all(p.vector_rank is not None for p in result.passages)


def test_retrieval_stays_inside_the_snapshots_it_is_given(sessions, add_snapshot):
    economy = add_snapshot(fixture_text("economy-call-3"))
    av = add_snapshot(fixture_text("av-measure-819"))
    not_indexed = add_snapshot(fixture_text("ipard-notice-03-2025"))
    index_pending(sessions, TopicEmbedder())
    with sessions() as session:
        # Stand-in for a document normalised after the last index run.
        session.execute(Chunk.__table__.delete().where(Chunk.snapshot_id == not_indexed))
        session.commit()

    with sessions() as session:
        result = hybrid_retrieve(
            session, TopicEmbedder(), [av, not_indexed], "машини и алати", k=20
        )

    assert result.passages
    assert {p.snapshot_id for p in result.passages} == {av}
    assert result.unindexed_snapshots == 1 and not result.complete
    assert economy not in {p.snapshot_id for p in result.passages}


def test_a_chunk_without_a_vector_is_still_found_by_trigram(sessions, add_snapshot):
    snapshot_id = add_snapshot(fixture_text("av-measure-819"))
    with sessions() as session:
        chunk_snapshot(session, session.get(RawSnapshot, snapshot_id))
        session.commit()

    with sessions() as session:
        result = hybrid_retrieve(session, TopicEmbedder(), [snapshot_id], "12.000,00 денари")

    assert "12.000,00 денари" in result.passages[0].text
    assert result.unembedded == len(chunks_of(sessions, snapshot_id))


def test_a_call_searches_the_latest_version_of_each_of_its_documents(sessions, feed, add_snapshot):
    old_day, new_day = (
        dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 9, 10, tzinfo=dt.UTC),
    )
    call_old = add_snapshot("рок 30.06.2026", url="https://gov.example/call", seen=old_day)
    call_new = add_snapshot("рок 15.07.2026", url="https://gov.example/call", seen=new_day)
    annex = add_snapshot("прилог", url="https://gov.example/annex", seen=old_day)
    add_snapshot("друг повик", url="https://gov.example/other", seen=new_day)

    with sessions() as session:
        programme = Programme(
            source_feed_id=feed.id, slug="test-retrieval", name_mk="Тест", institution="Тест"
        )
        session.add(programme)
        session.flush()
        call = Call(
            programme_id=programme.id, source_feed_id=feed.id, title_mk="Тест",
            canonical_url="https://gov.example/call", primary_snapshot_id=call_new,
        )  # fmt: skip
        session.add(call)
        session.flush()
        for snapshot_id in (call_old, call_new, annex):
            session.add(CallDocument(call_id=call.id, snapshot_id=snapshot_id, role="call_text"))
        session.commit()

        assert call_snapshot_ids(session, call.id) == sorted([call_new, annex])
