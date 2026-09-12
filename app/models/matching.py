"""Match runs, results, per-criterion outcomes and evidence.

A match_run is immutable and records the exact rule and weight versions used, so
any delivered report is reproducible months later.
"""

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, now_column, pg_enum, timestamptz, uuid_pk
from app.models.enums import ReviewKind, ReviewState, Verdict


class MatchRun(Base):
    __tablename__ = "match_run"
    __table_args__ = (Index("ix_match_run_profile", "profile_id", text("created_at DESC")),)

    id: Mapped[uuid.UUID] = uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applicant_profile.id", ondelete="CASCADE")
    )
    ruleset_version: Mapped[str] = mapped_column(String(50))
    weights_version: Mapped[str] = mapped_column(String(50))
    # 2 = free shortlist, 3 = verified, 4 = reviewed.
    stage_reached: Mapped[int] = mapped_column(SmallInteger)
    candidates_considered: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = now_column()


class MatchResult(Base):
    __tablename__ = "match_result"
    __table_args__ = (
        UniqueConstraint("match_run_id", "call_id", name="uq_match_result_run_call"),
        Index("ix_match_result_run", "match_run_id", "rank"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    match_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("match_run.id", ondelete="CASCADE"))
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("call.id", ondelete="CASCADE"))
    verdict: Mapped[Verdict] = mapped_column(pg_enum(Verdict, "verdict"))
    score: Mapped[float] = mapped_column(Numeric(6, 4))
    # {component: {value, weight, reason}} -- the reason strings are what the
    # shortlist prints, and what makes a ranking explainable a year later.
    score_breakdown: Mapped[dict] = mapped_column(JSONB)
    rank: Mapped[int] = mapped_column(Integer)


class MatchCriterionOutcome(Base):
    """One line item of the report: how a single criterion came out."""

    __tablename__ = "match_criterion_outcome"
    __table_args__ = (
        UniqueConstraint("match_result_id", "criterion_id", name="uq_outcome_result_criterion"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    match_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("match_result.id", ondelete="CASCADE")
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eligibility_criterion.id", ondelete="CASCADE")
    )
    verdict: Mapped[Verdict] = mapped_column(pg_enum(Verdict, "verdict"))
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    # 'rule' | 'model' | 'human'. Only 'rule' may yield not_eligible.
    decided_by: Mapped[str] = mapped_column(String(10))
    reason_mk: Mapped[str | None] = mapped_column(Text)


class Evidence(Base):
    """A retrieved passage backing one specific statement.

    Cites a snapshot and a character span, never a live URL, so the citation
    remains checkable after the source website changes.
    """

    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_outcome", "outcome_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    outcome_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("match_criterion_outcome.id", ondelete="CASCADE")
    )
    snapshot_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("raw_snapshot.id"))
    chunk_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("chunk.id"))
    quote: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    retrieved_at: Mapped[dt.datetime] = now_column()
    source_url: Mapped[str] = mapped_column(Text)
    section_ref: Mapped[str | None] = mapped_column(Text)


class ReviewQueueItem(Base):
    """The human gate: a first-class feature, not a workaround (brief section 6.4).

    corrected_payload holds the reviewer's diff, which a nightly job turns into an
    evaluation case. That loop is the point of the gate, not just quality control.
    """

    __tablename__ = "review_queue_item"
    __table_args__ = (
        Index(
            "ix_review_pending",
            "state",
            "priority",
            "created_at",
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[ReviewKind] = mapped_column(pg_enum(ReviewKind, "review_kind"))
    state: Mapped[ReviewState] = mapped_column(
        pg_enum(ReviewState, "review_state"), server_default=text("'pending'")
    )
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=text("100"))
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("call.id", ondelete="CASCADE"))
    match_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("match_run.id", ondelete="CASCADE")
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("order.id", ondelete="CASCADE"))
    payload: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    reason: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("account.id"))
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    corrected_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = now_column()
    resolved_at: Mapped[dt.datetime | None] = timestamptz()
