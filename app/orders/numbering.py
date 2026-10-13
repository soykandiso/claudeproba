"""Invoice numbers: gapless per kind and fiscal year (roadmap P4 s48, s54).

The next number is the highest issued this year plus one, read under a transaction-scoped
advisory lock, so two orders paid in the same second cannot take the same number and a
transaction that rolls back leaves no gap (its number was never written). An invoice is
never deleted (`invoice.order_id` is RESTRICT), so a number once issued stays issued.

The format is `config/invoicing.yaml`'s, provisional until the accountant confirms it (D4).

**The year is Skopje's** (P4 s54). The VPS keeps UTC; at 00:30 on 1 January in Skopje it is
still 31 December there. `today()` is the business date every proforma, payment and invoice
is dated by, so a document issued on New Year's night carries the new year in its number,
its date and its `fiscal_year`, which the database holds equal (`ck_invoice_fiscal_year`).

**A year's numbers are one series.** They are read by kind and `fiscal_year`, not by prefix:
if the prefix in `config/invoicing.yaml` changed during a year, numbering would otherwise
start again at 1 under the new prefix. It refuses instead (`NumberingError`): a prefix
changes on 1 January, with the accountant, or not at all.

`audit()` (`flask invoices audit`) reads every series back: gaps, duplicates, numbers in
another format, a year that disagrees with the issue date. It should always print nothing.
"""

import datetime as dt
import re
from collections import defaultdict
from functools import cache
from pathlib import Path

import yaml
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.commerce import Invoice
from app.models.enums import InvoiceKind
from app.web.format import SKOPJE

CONFIG = Path(__file__).resolve().parents[2] / "config" / "invoicing.yaml"


class NumberingError(RuntimeError):
    """The series cannot be continued without a gap, a duplicate or a mixed format."""


@cache
def settings() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)  # the server's clock; the tests set it


def today() -> dt.date:
    """The business date: Skopje's, whatever the server's clock is set to."""
    return now().astimezone(SKOPJE).date()


def _format(prefix: str, year: int) -> re.Pattern:
    return re.compile(rf"^{re.escape(prefix)}-{year}-(\d{{4,}})$")


def next_number(session: Session, kind: InvoiceKind, year: int) -> str:
    """The next free number of this kind this year; call inside the transaction that uses it."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"invoice:{kind}:{year}"}
    )
    prefix = settings()["prefixes"][str(kind)]
    form = _format(prefix, year)
    issued = session.scalars(
        select(Invoice.number).where(Invoice.kind == kind, Invoice.fiscal_year == year)
    ).all()
    foreign = sorted(n for n in issued if not form.match(n))
    if foreign:
        raise NumberingError(
            f"{kind} {year}: {', '.join(foreign[:3])} are not {prefix}-{year}-NNNN; "
            "the prefix changed during the year (config/invoicing.yaml)"
        )
    highest = max((int(form.match(n).group(1)) for n in issued), default=0)
    return f"{prefix}-{year}-{highest + 1:04d}"


def audit(session: Session) -> list[str]:
    """Everything wrong with the issued series, one line each; empty when all is well."""
    problems, series = [], defaultdict(list)
    rows = session.execute(
        select(Invoice.kind, Invoice.fiscal_year, Invoice.number, Invoice.issued_at)
    )
    for kind, year, number, issued_at in rows:
        series[(str(kind), year)].append(number)
        if issued_at.year != year:
            problems.append(f"{number}: issued {issued_at:%d.%m.%Y} but in fiscal year {year}")
    for (kind, year), numbers in sorted(series.items()):
        form = _format(settings()["prefixes"][kind], year)
        problems += [f"{n}: not the {kind} format for {year}" for n in numbers if not form.match(n)]
        seen = sorted(int(m.group(1)) for n in numbers if (m := form.match(n)))
        if len(seen) != len(set(seen)):
            problems.append(f"{kind} {year}: a number is issued twice")
        missing = sorted(set(range(1, max(seen, default=0) + 1)) - set(seen))
        if missing:
            shown = ", ".join(f"{m:04d}" for m in missing[:10])
            problems.append(f"{kind} {year}: missing {shown}")
    return problems
