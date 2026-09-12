"""Model tests against a real PostgreSQL.

Skipped when no database is reachable, so the default `pytest` run stays fast and
needs no services. Run the compose stack to exercise them.

These cover the parts of the schema that carry the accuracy contract and the
matching hot path -- the places where being wrong is expensive and where an
in-memory substitute would prove nothing, because the behaviour under test is
PostgreSQL's.
"""

import uuid

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import load_settings
from app.models import Call, EligibilityCriterion, Programme, RawSnapshot, SourceFeed
from app.models.enums import AccessMethod, CallStatus, CriterionKind, EntityType

settings = load_settings()

try:
    with psycopg.connect(settings.database_url, connect_timeout=2):
        DATABASE_AVAILABLE = True
except Exception:
    DATABASE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)


@pytest.fixture
def session():
    """A session whose work is always rolled back, so tests leave no residue."""
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    with Session(bind=connection) as s:
        yield s
    # A test that asserts on IntegrityError has already rolled the transaction
    # back; rolling back again warns.
    if transaction.is_active:
        transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def call(session):
    feed = SourceFeed(
        slug=f"test-{uuid.uuid4().hex[:8]}",
        name_mk="Фонд за иновации и технолошки развој",
        name_en="Fund for Innovation and Technology Development",
        institution="ФИТР",
        base_url="https://example.invalid",
        access_method=AccessMethod.HTML,
        expected_cadence="30 days",
        staleness_sla="60 days",
    )
    session.add(feed)
    session.flush()

    programme = Programme(
        source_feed_id=feed.id,
        slug=f"programme-{uuid.uuid4().hex[:8]}",
        name_mk="Кофинансирани грантови за новоосновани трговски друштва",
        institution="ФИТР",
    )
    session.add(programme)
    session.flush()

    snapshot = RawSnapshot(
        source_feed_id=feed.id,
        url="https://example.invalid/povik/1",
        content_sha256="a" * 64,
        http_status=200,
        storage_key="snapshots/test/aaa",
        normalised_text="Право на учество имаат микро и мали претпријатија основани во РСМ.",
    )
    session.add(snapshot)
    session.flush()

    call = Call(
        programme_id=programme.id,
        source_feed_id=feed.id,
        title_mk="Јавен повик за кофинансирани грантови",
        canonical_url="https://example.invalid/povik/1",
        status=CallStatus.OPEN,
        is_published=True,
        deadline_at=text("now() + interval '30 days'"),
        allowed_entity_types=[EntityType.MICRO, EntityType.SMALL],
        allowed_nace_prefixes=["62", "63"],
        primary_snapshot_id=snapshot.id,
    )
    session.add(call)
    session.flush()
    call.snapshot_id = snapshot.id
    return call


def test_approved_criterion_requires_a_citation(session, call):
    """'No citation, no claim' is enforced by the database, not by discipline.

    This is CLAUDE.md invariant 2. If it can be violated by an INSERT, it is not
    an invariant.
    """
    session.add(
        EligibilityCriterion(
            call_id=call.id,
            kind=CriterionKind.HARD_STRUCTURED,
            label_mk="Возраст на компанијата",
            field="age_months",
            operator="lte",
            value_json=60,
            is_approved=True,  # approved, but no source_quote and no snapshot_id
        )
    )
    with pytest.raises(IntegrityError, match="has_citation"):
        session.flush()


def test_hard_structured_criterion_requires_a_predicate(session, call):
    """A hard rule with no field or operator could never be evaluated."""
    session.add(
        EligibilityCriterion(
            call_id=call.id,
            kind=CriterionKind.HARD_STRUCTURED,
            label_mk="Нешто немерливо",
        )
    )
    with pytest.raises(IntegrityError, match="structured_has_predicate"):
        session.flush()


def test_narrative_criterion_needs_no_predicate(session, call):
    """Narrative criteria are verified against retrieved text, not evaluated."""
    session.add(
        EligibilityCriterion(
            call_id=call.id,
            kind=CriterionKind.NARRATIVE_VERIFY,
            label_mk="Проектот мора да покаже иновативен потенцијал",
        )
    )
    session.flush()  # must not raise


def test_hard_filter_overlap_query_matches_on_entity_type(session, call):
    """Stage 1 of matching: the denormalised array columns and their overlap test.

    An empty array means 'no restriction', which is what keeps the filter a single
    overlap test instead of a nullable special case (docs/matching.md section 3).
    """
    matched = session.execute(
        text("""
            SELECT id FROM call
            WHERE is_published AND status = 'open'
              AND (deadline_at IS NULL OR deadline_at > now())
              AND (allowed_entity_types = '{}'
                   OR allowed_entity_types && ARRAY[:entity]::entity_type[])
              AND (allowed_nace_prefixes = '{}'
                   OR allowed_nace_prefixes && :nace)
              AND id = :call_id
        """),
        {"entity": "micro", "nace": ["62.01", "62", "J"], "call_id": call.id},
    ).fetchall()
    assert len(matched) == 1

    excluded = session.execute(
        text("""
            SELECT id FROM call
            WHERE allowed_entity_types && ARRAY[:entity]::entity_type[] AND id = :call_id
        """),
        {"entity": "municipality", "call_id": call.id},
    ).fetchall()
    assert excluded == []


def test_macedonian_specific_characters_round_trip(session, call):
    """The letters unique to Macedonian Cyrillic must survive unchanged.

    Ѓ Ќ Љ Њ Џ Ѕ Ј are exactly the characters a wrong encoding or an incomplete
    font subset loses, and losing them in stored data is unrecoverable (brief 3.1).
    """
    alphabet = "ЃѓЌќЉљЊњЏџЅѕЈј"
    call.summary_mk = f"Проверка: {alphabet}"
    session.flush()
    session.expire(call)

    stored = session.get(Call, call.id)
    assert stored.summary_mk == f"Проверка: {alphabet}"
    assert all(char in stored.summary_mk for char in alphabet)
    assert stored.title_mk == "Јавен повик за кофинансирани грантови"
    assert stored.allowed_entity_types == [EntityType.MICRO, EntityType.SMALL]
