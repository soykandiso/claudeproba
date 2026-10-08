"""Invoice numbers: gapless per kind and fiscal year (roadmap P4 s48, s54).

The next number is the highest issued this year plus one, read under a transaction-scoped
advisory lock, so two orders paid in the same second cannot take the same number and a
transaction that rolls back leaves no gap (its number was never written). An invoice is
never deleted (`invoice.order_id` is RESTRICT), so a number once issued stays issued.

The format is `config/invoicing.yaml`'s, provisional until the accountant confirms it (D4).
"""

from functools import cache
from pathlib import Path

import yaml
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.commerce import Invoice
from app.models.enums import InvoiceKind

CONFIG = Path(__file__).resolve().parents[2] / "config" / "invoicing.yaml"


@cache
def settings() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def next_number(session: Session, kind: InvoiceKind, year: int) -> str:
    """The next free number of this kind this year; call inside the transaction that uses it."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"invoice:{kind}:{year}"}
    )
    prefix = settings()["prefixes"][str(kind)]
    pattern = f"{prefix}-{year}-%"
    issued = session.scalars(
        select(Invoice.number).where(Invoice.kind == kind, Invoice.number.like(pattern))
    ).all()
    highest = max((int(number.rsplit("-", 1)[-1]) for number in issued), default=0)
    return f"{prefix}-{year}-{highest + 1:04d}"
