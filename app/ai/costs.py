"""What the model costs (P2 s36): this month against the ceiling, by task, by report.

Read from `model_call`, which the gateway writes for every attempt (cache hits at zero,
failures with whatever they cost). `cost_usd` is the gateway's estimate from
`config/models.yaml`'s list prices; **the provider's invoice is the authority**, and
this is the number to watch between invoices.

Three readings, for `/admin/troshoci` and `flask ingest health`:

- **month to date** against decisions.md D8's ceiling (`GRANTS_MODEL_SPEND_CEILING_EUR`),
  converted at `eur_per_usd` from `config/models.yaml`, a rate written down by hand:
  the ceiling is an alarm, not a bill, and a rate a few cents off changes nothing;
- **by task**, so a month that costs more says which work cost it;
- **by report**: the model calls of each delivered report's match run (verification
  and composition), which is the marginal model cost of one report the roadmap asks for.

Months are Skopje's calendar months, like the invoices'.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.ai.gateway import DEFAULT_ROUTING
from app.models import ModelCall, Order, Product


def eur_per_usd(path: Path = DEFAULT_ROUTING) -> float:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return float(raw["eur_per_usd"])


def month_start(now: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    """Midnight on the first of `now`'s month in Skopje, as an aware datetime."""
    local = now.astimezone(tz)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _previous_month(start: dt.datetime) -> dt.datetime:
    return (start - dt.timedelta(days=1)).replace(day=1)


@dataclass(frozen=True)
class TaskCost:
    task: str
    calls: int
    cached: int
    failed: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def by_task(session: Session, since: dt.datetime, until: dt.datetime | None = None):
    """One row per task between `since` and `until`, the dearest first."""
    cost = func.coalesce(func.sum(ModelCall.cost_usd), 0)
    query = (
        select(
            ModelCall.task,
            func.count(),
            func.count().filter(ModelCall.cache_hit.is_(True)),
            func.count().filter(ModelCall.ok.is_(False)),
            func.coalesce(func.sum(ModelCall.input_tokens), 0),
            func.coalesce(func.sum(ModelCall.output_tokens), 0),
            cost,
        )
        .where(ModelCall.created_at >= since)
        .group_by(ModelCall.task)
        .order_by(cost.desc(), ModelCall.task)
    )
    if until is not None:
        query = query.where(ModelCall.created_at < until)
    return [
        TaskCost(task, calls, cached, failed, int(i), int(o), float(c))
        for task, calls, cached, failed, i, o, c in session.execute(query)
    ]


def spent_usd(session: Session, since: dt.datetime, until: dt.datetime | None = None) -> float:
    query = select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(
        ModelCall.created_at >= since
    )
    if until is not None:
        query = query.where(ModelCall.created_at < until)
    return float(session.scalar(query))


@dataclass(frozen=True)
class Month:
    start: dt.datetime
    calls: int
    cost_usd: float


def by_month(session: Session, now: dt.datetime, tz: ZoneInfo, months: int = 12) -> list[Month]:
    """The last `months` calendar months, this one first, empty months included."""
    starts = [month_start(now, tz)]
    while len(starts) < months:
        starts.append(_previous_month(starts[-1]))
    found = []
    for i, start in enumerate(starts):
        until = starts[i - 1] if i else None
        query = select(func.count(), func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(
            ModelCall.created_at >= start
        )
        if until is not None:
            query = query.where(ModelCall.created_at < until)
        calls, cost = session.execute(query).one()
        found.append(Month(start, calls, float(cost)))
    return found


@dataclass(frozen=True)
class ReportCost:
    order_id: uuid.UUID
    delivered_at: dt.datetime
    calls: int
    cached: int
    cost_usd: float


def per_report(session: Session, limit: int = 20) -> list[ReportCost]:
    """The model cost of each of the last `limit` delivered reports, newest first."""
    rows = session.execute(
        select(
            Order.id,
            Order.delivered_at,
            func.count(ModelCall.id),
            func.count(case((ModelCall.cache_hit.is_(True), 1))),
            func.coalesce(func.sum(ModelCall.cost_usd), 0),
        )
        .join(Product, Product.id == Order.product_id)
        .outerjoin(ModelCall, ModelCall.match_run_id == Order.match_run_id)
        .where(
            Product.sku == "report",
            Order.delivered_at.is_not(None),
            Order.match_run_id.is_not(None),
        )
        .group_by(Order.id, Order.delivered_at)
        .order_by(Order.delivered_at.desc())
        .limit(limit)
    )
    return [ReportCost(o, at, n, c, float(cost)) for o, at, n, c, cost in rows]


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


@dataclass(frozen=True)
class Spend:
    """This month so far, against the ceiling."""

    since: dt.datetime
    usd: float
    eur: float
    ceiling_eur: float

    @property
    def over(self) -> bool:
        return self.eur > self.ceiling_eur

    @property
    def share(self) -> float:
        return self.eur / self.ceiling_eur if self.ceiling_eur else 0.0


def month_to_date(
    session: Session, now: dt.datetime, tz: ZoneInfo, ceiling_eur: float, rate: float
) -> Spend:
    since = month_start(now, tz)
    usd = spent_usd(session, since, now)
    return Spend(since, usd, usd * rate, ceiling_eur)
