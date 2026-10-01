"""Document templates and generated packages (P5).

Templates are version-controlled files; these tables record which version produced
which output, so a delivered package is reproducible.
"""

import datetime as dt
import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, now_column, pg_enum, timestamptz, uuid_pk
from app.models.enums import Lang, ReviewState


class DocumentTemplate(Base):
    __tablename__ = "document_template"
    __table_args__ = (
        UniqueConstraint("programme_id", "slug", "version", name="uq_document_template_version"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    programme_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("programme.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str] = mapped_column(Text)
    lang: Mapped[Lang] = mapped_column(pg_enum(Lang, "lang"), server_default=text("'mk'"))
    required_fields: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))


class DocumentPackage(Base):
    __tablename__ = "document_package"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order.id", ondelete="CASCADE"))
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("call.id"))
    state: Mapped[ReviewState] = mapped_column(
        pg_enum(ReviewState, "review_state"), server_default=text("'pending'")
    )
    # What the applicant must still provide: signatures, certificates, bank
    # confirmations (brief section 8).
    checklist: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[dt.datetime] = now_column()
    delivered_at: Mapped[dt.datetime | None] = timestamptz()


class GeneratedDocument(Base):
    __tablename__ = "generated_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_package.id", ondelete="CASCADE")
    )
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_template.id"))
    storage_key: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(10))
    is_ai_assisted: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    human_reviewed_at: Mapped[dt.datetime | None] = timestamptz()
    # Financial projections and legal declarations are never auto-filled with
    # invented figures; they are listed here as fields the applicant must supply.
    unfilled_fields: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
