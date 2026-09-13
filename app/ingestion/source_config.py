"""config/sources.yaml → source_feed rows."""

import datetime as dt
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceFeed
from app.models.enums import AccessMethod

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "sources.yaml"


class SourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in the file is an error, not ignored

    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    name_mk: str
    name_en: str
    institution: str
    base_url: str
    access_method: AccessMethod
    expected_cadence_days: int = Field(gt=0)
    staleness_sla_days: int = Field(gt=0)
    rate_limit_rps: float = Field(gt=0, le=1)
    terms_url: str | None = None
    terms_note: str | None = None
    priority: int = 100
    active: bool = False


def load_sources(path: Path = DEFAULT_PATH) -> list[SourceEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = [SourceEntry.model_validate(item) for item in raw.get("sources") or []]
    slugs = [e.slug for e in entries]
    if len(slugs) != len(set(slugs)):
        raise ValueError(f"duplicate slug in {path}")
    return entries


def sync_sources(session: Session, entries: list[SourceEntry]) -> list[str]:
    """Create or update a row per entry. Returns what changed, for the operator to read.

    Sources removed from the file are deactivated, never deleted: their snapshots
    and calls are the audit trail.
    """
    existing = {s.slug: s for s in session.scalars(select(SourceFeed))}
    changes = []
    for entry in entries:
        values = {
            "name_mk": entry.name_mk,
            "name_en": entry.name_en,
            "institution": entry.institution,
            "base_url": entry.base_url,
            "access_method": entry.access_method,
            "expected_cadence": dt.timedelta(days=entry.expected_cadence_days),
            "staleness_sla": dt.timedelta(days=entry.staleness_sla_days),
            "rate_limit_rps": entry.rate_limit_rps,
            "terms_url": entry.terms_url,
            "terms_note": entry.terms_note,
            "priority": entry.priority,
            "is_active": entry.active,
        }
        row = existing.pop(entry.slug, None)
        if row is None:
            session.add(SourceFeed(slug=entry.slug, **values))
            changes.append(f"created {entry.slug}")
            continue
        changed = [k for k, v in values.items() if _differs(getattr(row, k), v)]
        for key in changed:
            setattr(row, key, values[key])
        if changed:
            changes.append(f"updated {entry.slug}: {', '.join(changed)}")
    for row in existing.values():
        if row.is_active:
            row.is_active = False
            changes.append(f"deactivated {row.slug} (no longer in the file)")
    session.flush()
    return changes


def _differs(current, new) -> bool:
    if isinstance(new, float) and current is not None:
        return abs(float(current) - new) > 1e-9
    return current != new
