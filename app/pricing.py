"""Prices, from `config/prices.yaml` (roadmap P3 s39, docs/decisions.md D1).

One place says what anything costs, and the page reads it: a price is never typed into a
template, so the pricing page, a future order form and an invoice cannot disagree. ДДВ is
computed here, once, and shown beside every net price.
"""

from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "prices.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)  # a typo is an error


class Founding(_Strict):
    net: int = Field(gt=0)
    orders: int = Field(gt=0)
    open: bool


class Report(_Strict):
    net: int = Field(gt=0)
    founding: Founding
    orderable: bool


class Monitoring(_Strict):
    monthly_net: int = Field(gt=0)
    yearly_net: int = Field(gt=0)
    available: bool


class Prices(_Strict):
    vat_percent: int = Field(ge=0, le=100)
    report: Report
    monitoring: Monitoring

    def gross(self, net: int) -> int:
        """With ДДВ, to the whole denar, half up: 8.900 → 10.502."""
        value = Decimal(net) * (100 + self.vat_percent) / 100
        return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@cache
def prices(path: Path = DEFAULT_PATH) -> Prices:
    return Prices.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
