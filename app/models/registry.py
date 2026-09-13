"""Sources, snapshots and the funding registry.

Ingestion provenance is the backbone of the accuracy contract: if you cannot say
where a fact came from and when, you cannot publish it (CLAUDE.md invariant 2).
"""

import datetime as dt
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Interval,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, now_column, pg_enum, timestamptz, uuid_pk
from app.models.enums import AccessMethod, CallStatus, CriterionKind, EntityType


class SourceFeed(Base):
    """One institution or feed we crawl.

    Cadence and SLA drive the staleness alarm, which is the most important
    operational alert in the system: a silently dead scraper is the primary
    business failure mode (docs/risks.md R1).
    """

    __tablename__ = "source_feed"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name_mk: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    institution: Mapped[str] = mapped_column(Text)
    base_url: Mapped[str] = mapped_column(Text)
    access_method: Mapped[AccessMethod] = mapped_column(pg_enum(AccessMethod, "access_method"))
    robots_checked_at: Mapped[dt.datetime | None] = timestamptz()
    terms_url: Mapped[str | None] = mapped_column(Text)
    terms_note: Mapped[str | None] = mapped_column(Text)
    expected_cadence: Mapped[dt.timedelta] = mapped_column(Interval)
    staleness_sla: Mapped[dt.timedelta] = mapped_column(Interval)
    rate_limit_rps: Mapped[float] = mapped_column(Numeric(5, 2), server_default=text("0.2"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=text("100"))
    created_at: Mapped[dt.datetime] = now_column()


class SourceHealth(Base):
    """Per-run health state.

    Separate from source_feed so a hot per-run write does not contend with
    configuration reads.
    """

    __tablename__ = "source_health"

    source_feed_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_feed.id", ondelete="CASCADE"), primary_key=True
    )
    last_attempt_at: Mapped[dt.datetime | None] = timestamptz()
    last_success_at: Mapped[dt.datetime | None] = timestamptz()
    last_new_item_at: Mapped[dt.datetime | None] = timestamptz()
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    is_alerting: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class IngestionRun(Base):
    """One crawl execution.

    Gives a post-mortem when an overnight run goes wrong -- the reason the stack
    uses cron plus RQ rather than an in-process scheduler.
    """

    __tablename__ = "ingestion_run"
    __table_args__ = (
        Index("ix_ingestion_run_source_time", "source_feed_id", text("started_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_feed_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_feed.id", ondelete="CASCADE")
    )
    started_at: Mapped[dt.datetime] = now_column()
    finished_at: Mapped[dt.datetime | None] = timestamptz()
    ok: Mapped[bool | None] = mapped_column(Boolean)
    urls_seen: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    urls_changed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    items_created: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    items_updated: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    queued_for_review: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)


class RawSnapshot(Base):
    """What a URL returned. The content never changes once written; see last_seen_at.

    The bytes live in object storage; only the pointer and hash are here, so
    nightly pg_dump stays small and restores stay fast. normalised_text IS stored,
    because citations index into it by character offset and must survive
    independently of the parser version that produced them.
    """

    __tablename__ = "raw_snapshot"
    __table_args__ = (
        UniqueConstraint("url", "content_sha256", name="uq_raw_snapshot_url_hash"),
        Index("ix_snapshot_url_time", "url", text("fetched_at DESC")),
        Index("ix_snapshot_url_seen", "url", text("last_seen_at DESC")),
        Index("ix_snapshot_hash", "content_sha256"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_feed_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_feed.id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    http_status: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(Text)
    byte_length: Mapped[int | None] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime] = now_column()
    # The one mutable column: bumped each time the same bytes are fetched again.
    # It answers "is this still what the source says?" (last_verified_at in the
    # UI), and it keeps "current content for this URL" correct when a page
    # changes and then reverts to bytes already stored.
    last_seen_at: Mapped[dt.datetime] = now_column()
    normalised_text: Mapped[str | None] = mapped_column(Text)
    normaliser_version: Mapped[str | None] = mapped_column(Text)


class Programme(Base):
    """A durable funding instrument, surviving across years and individual calls.

    Kept separate from Call because criteria, templates and institutional
    knowledge change slowly, the SEO archive wants stable pages, and the
    monitoring subscription is naturally "tell me when this reopens". One-off
    calls get an auto-created programme with is_singleton set.
    """

    __tablename__ = "programme"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_feed_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_feed.id"))
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    name_mk: Mapped[str] = mapped_column(Text)
    name_sq: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    institution: Mapped[str] = mapped_column(Text)
    description_mk: Mapped[str | None] = mapped_column(Text)
    is_singleton: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    typical_cadence: Mapped[dt.timedelta | None] = mapped_column(Interval)
    created_at: Mapped[dt.datetime] = now_column()


class Call(Base):
    """A dated instance of a programme: what an applicant actually applies to."""

    __tablename__ = "call"
    __table_args__ = (
        # The hot path: published, open, deadline ahead. Stage 1 of matching
        # touches only the denormalised columns below (docs/matching.md section 3).
        Index(
            "ix_call_open",
            "status",
            "deadline_at",
            postgresql_where=text("is_published AND status = 'open'"),
        ),
        Index("ix_call_entity_types", "allowed_entity_types", postgresql_using="gin"),
        Index("ix_call_nace", "allowed_nace_prefixes", postgresql_using="gin"),
        Index("ix_call_regions", "allowed_regions", postgresql_using="gin"),
        Index("ix_call_programme", "programme_id", text("published_at DESC")),
        Index(
            "ix_call_title_trgm",
            "title_mk",
            postgresql_using="gin",
            postgresql_ops={"title_mk": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    programme_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("programme.id", ondelete="RESTRICT"))
    source_feed_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_feed.id"))
    reference_code: Mapped[str | None] = mapped_column(Text)
    title_mk: Mapped[str] = mapped_column(Text)
    title_sq: Mapped[str | None] = mapped_column(Text)
    title_en: Mapped[str | None] = mapped_column(Text)
    summary_mk: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CallStatus] = mapped_column(
        pg_enum(CallStatus, "call_status"), server_default=text("'draft'")
    )
    published_at: Mapped[dt.date | None] = mapped_column(Date)
    opens_at: Mapped[dt.date | None] = mapped_column(Date)
    deadline_at: Mapped[dt.datetime | None] = timestamptz()
    total_budget_mkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    total_budget_eur: Mapped[float | None] = mapped_column(Numeric(14, 2))
    grant_min_mkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    grant_max_mkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    cofinancing_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))

    # Denormalised hard-filter columns. An empty array means "no restriction",
    # which keeps the filter a single overlap test instead of a nullable case.
    allowed_entity_types: Mapped[list[EntityType]] = mapped_column(
        ARRAY(pg_enum(EntityType, "entity_type")), server_default=text("'{}'")
    )
    allowed_nace_prefixes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    allowed_regions: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    min_company_age_months: Mapped[int | None] = mapped_column(Integer)
    max_company_age_months: Mapped[int | None] = mapped_column(Integer)

    canonical_url: Mapped[str] = mapped_column(Text)
    primary_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("raw_snapshot.id")
    )
    # Surfaced in the UI on every call, per brief section 12.
    last_verified_at: Mapped[dt.datetime] = now_column()
    extraction_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    # False until a human approves the extraction.
    is_published: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[dt.datetime] = now_column()
    updated_at: Mapped[dt.datetime] = now_column()


class CallDocument(Base):
    """A document belonging to a call.

    Separate from the call so a 40-page guideline and a 2-page form are chunked
    and retrieved independently.
    """

    __tablename__ = "call_document"
    __table_args__ = (Index("ix_call_document_call", "call_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("call.id", ondelete="CASCADE"))
    snapshot_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("raw_snapshot.id"))
    role: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class EligibilityCriterion(Base):
    """The central table of the accuracy contract.

    kind decides who evaluates it and whether it may exclude an applicant. Only
    hard_structured can produce 'not eligible'; anything the model touches caps at
    'needs verification'. The citation columns make every criterion auditable
    months later, and the check constraint makes "no citation, no claim"
    enforceable by the database rather than by discipline.
    """

    __tablename__ = "eligibility_criterion"
    __table_args__ = (
        CheckConstraint(
            "kind <> 'hard_structured' OR (field IS NOT NULL AND operator IS NOT NULL)",
            name="structured_has_predicate",
        ),
        CheckConstraint(
            "NOT is_approved OR (snapshot_id IS NOT NULL AND source_quote IS NOT NULL)",
            name="has_citation",
        ),
        Index("ix_criterion_call", "call_id", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("call.id", ondelete="CASCADE"))
    kind: Mapped[CriterionKind] = mapped_column(pg_enum(CriterionKind, "criterion_kind"))
    code: Mapped[str | None] = mapped_column(String(100))
    label_mk: Mapped[str] = mapped_column(Text)

    # Machine-evaluable form; null for narrative, attest and documentary kinds.
    field: Mapped[str | None] = mapped_column(String(100))
    operator: Mapped[str | None] = mapped_column(String(20))
    value_json: Mapped[dict | None] = mapped_column(JSONB)

    # Ranking weight; used only by kind='soft_scored'.
    weight: Mapped[float | None] = mapped_column(Numeric(4, 2))

    source_quote: Mapped[str | None] = mapped_column(Text)
    snapshot_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raw_snapshot.id"))
    quote_start: Mapped[int | None] = mapped_column(Integer)
    quote_end: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    extracted_at: Mapped[dt.datetime] = now_column()
    prompt_version: Mapped[str | None] = mapped_column(Text)
    is_approved: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Chunk(Base):
    """Retrieval unit: one chunk of one snapshot, with offsets back into it.

    Hybrid retrieval -- vector for prose, trigram for codes, numbers and dates.
    pgvector earns its place here for a specific reason: PostgreSQL has no
    Macedonian full-text dictionary, so lexical-only retrieval over Cyrillic
    would be weak.
    """

    __tablename__ = "chunk"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "ordinal", name="uq_chunk_snapshot_ordinal"),
        Index("ix_chunk_call", "call_id"),
        Index(
            "ix_chunk_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_chunk_text_trgm",
            "text",
            postgresql_using="gin",
            postgresql_ops={"text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_snapshot.id", ondelete="CASCADE")
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("call.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    embedding_model: Mapped[str | None] = mapped_column(Text)
