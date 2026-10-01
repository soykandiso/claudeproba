"""Prompt versions and the model-call audit trail.

Every model call is recorded with its cost, which is how a feature's expense
becomes visible before the monthly invoice makes it visible (brief section 7).
"""

import datetime as dt
import uuid

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, now_column, timestamptz


class PromptVersion(Base):
    """Prompts are versioned files in prompts/; this records which ones ran."""

    __tablename__ = "prompt_version"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    task: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = now_column()


class ModelCall(Base):
    __tablename__ = "model_call"
    __table_args__ = (
        Index("ix_model_call_cost", text("created_at DESC"), "task"),
        Index("ix_model_call_cache", "input_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task: Mapped[str] = mapped_column(String(50))
    prompt_version_id: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("prompt_version.id")
    )
    model: Mapped[str] = mapped_column(String(100))
    cache_hit: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    input_hash: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)
    validation_error: Mapped[str | None] = mapped_column(Text)
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("call.id", ondelete="SET NULL"))
    match_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("match_run.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = now_column()


class ModelCallPayload(Base):
    """Full prompt and response audit storage.

    Separate from model_call because these rows are large, rarely read, and pruned
    on a different retention schedule. request_json holds exactly what left the
    building after scrubbing, which makes the minimisation claim auditable rather
    than merely asserted.
    """

    __tablename__ = "model_call_payload"

    model_call_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_call.id", ondelete="CASCADE"), primary_key=True
    )
    request_json: Mapped[dict] = mapped_column(JSONB)
    response_json: Mapped[dict | None] = mapped_column(JSONB)


class EmailEvent(Base):
    __tablename__ = "email_event"
    __table_args__ = (Index("ix_email_account", "account_id", text("sent_at DESC")),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(50))
    sent_at: Mapped[dt.datetime] = now_column()
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[dt.datetime | None] = timestamptz()
    bounced: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
