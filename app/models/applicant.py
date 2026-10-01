"""Accounts and applicant profiles.

Split deliberately (docs/architecture.md section 9.3): account is who they are,
applicant_profile is what they told us, versioned. A profile edited after a report
was purchased must not change the inputs that report was computed from.
"""

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, now_column, pg_enum, timestamptz, uuid_pk
from app.models.enums import EntityType, Lang


class Account(Base):
    __tablename__ = "account"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    email_verified_at: Mapped[dt.datetime | None] = timestamptz()
    preferred_lang: Mapped[Lang] = mapped_column(pg_enum(Lang, "lang"), server_default=text("'mk'"))
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[dt.datetime] = now_column()
    last_seen_at: Mapped[dt.datetime | None] = timestamptz()
    # GDPR erasure without destroying invoice rows the tax authority requires.
    anonymised_at: Mapped[dt.datetime | None] = timestamptz()


class ConsentRecord(Base):
    """Purpose-scoped consent.

    Service consent and marketing consent are separate rows and are never
    inferred from one another.
    """

    __tablename__ = "consent_record"
    __table_args__ = (
        Index("ix_consent_account", "account_id", "purpose", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(50))
    granted: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[str] = mapped_column(String(50))
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[dt.datetime] = now_column()


class ApplicantProfile(Base):
    """Immutable once superseded; a purchased report points at an exact version."""

    __tablename__ = "applicant_profile"
    __table_args__ = (Index("ix_profile_account", "account_id", text("version DESC")),)

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    superseded_at: Mapped[dt.datetime | None] = timestamptz()
    label: Mapped[str | None] = mapped_column(Text)

    # The intake answers exactly as stage 0 read them: the one input a match run
    # re-normalises from (app/matching/normalise.py). The typed columns below are
    # filled from it where an answer is exact, for queries; a band is not a number,
    # so headcount and investment size stay empty when only a band was given.
    answers: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    entity_type: Mapped[EntityType] = mapped_column(pg_enum(EntityType, "entity_type"))
    nace_code: Mapped[str | None] = mapped_column(String(10))
    municipality_code: Mapped[str | None] = mapped_column(String(20))
    region_code: Mapped[str | None] = mapped_column(String(20))
    founded_year: Mapped[int | None] = mapped_column(SmallInteger)
    headcount: Mapped[int | None] = mapped_column(Integer)
    # Banded rather than exact: data minimisation by design (brief section 3.3).
    turnover_band_mkd: Mapped[str | None] = mapped_column(String(50))
    is_woman_owned: Mapped[bool | None] = mapped_column(Boolean)
    is_youth_owned: Mapped[bool | None] = mapped_column(Boolean)
    is_export_oriented: Mapped[bool | None] = mapped_column(Boolean)
    investment_type: Mapped[str | None] = mapped_column(Text)
    investment_size_mkd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    cofinancing_capable_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    timeline_months: Mapped[int | None] = mapped_column(SmallInteger)
    project_keywords: Mapped[str | None] = mapped_column(Text)
    project_description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = now_column()
