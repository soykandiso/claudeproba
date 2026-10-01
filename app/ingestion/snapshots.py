"""Snapshot store and change detector (docs/architecture.md §3.1).

Bytes are written once, under a key derived from their SHA-256, to a directory on
a Docker volume; ops/backup.sh copies that directory off-site each night. The
architecture originally named S3 here. A directory plus the rclone copy the
backup already does gives the same guarantees -- write-once, off-site, EU --
without an S3 client library or a MinIO container, and a content-addressed file
never changes, so the nightly copy only ever uploads new ones.

The change detector is the main cost control in the system: bytes identical to
what a URL last returned create no row, write no file, and queue nothing for
analysis. They only move `last_seen_at`.
"""

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.http import Response
from app.models import RawSnapshot, SourceFeed


class CorruptSnapshot(RuntimeError):
    pass


Significant = Callable[[bytes], bytes]
"""Reduces a response to the part that matters for change detection."""


def all_bytes(content: bytes) -> bytes:
    return content


_ASPNET_STATE = re.compile(
    rb'(<input[^>]*name="__(?:VIEWSTATE|VIEWSTATEGENERATOR|EVENTVALIDATION|REQUESTDIGEST'
    rb'|RequestVerificationToken)"'
    rb'[^>]*value=")[^"]*(")',
    re.IGNORECASE,
)


def without_aspnet_state(content: bytes) -> bytes:
    """ASP.NET pages carry a __VIEWSTATE the server regenerates on every request.

    Observed on av.gov.mk on 13.09.2026: the same listing returned different bytes
    seven seconds apart, identical except for that field. Hashing raw bytes would
    call such a page changed on every run. ASP.NET MVC's anti-forgery field,
    __RequestVerificationToken, does the same (ipardpa.gov.mk, 16.09.2026).
    """
    return _ASPNET_STATE.sub(rb"\1\2", content)


class SnapshotStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    @staticmethod
    def key_for(source_slug: str, sha256: str) -> str:
        return f"snapshots/{source_slug}/{sha256}"

    def put(self, key: str, content: bytes) -> None:
        path = self._path(key)
        if path.exists():
            return  # content-addressed: the same key is always the same bytes
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename, so a crash never leaves a truncated file under a real key.
        tmp = path.with_name(f".{path.name}.tmp")
        with open(tmp, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        content = self._path(key).read_bytes()
        if not key.endswith(hashlib.sha256(content).hexdigest()):
            raise CorruptSnapshot(f"{key} does not match its own hash")
        return content

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"snapshot key escapes the store: {key}")
        return path


@dataclass(frozen=True)
class Recorded:
    snapshot: RawSnapshot
    changed: bool
    """True when these bytes differ from what the URL returned last time."""


def record(
    session: Session,
    store: SnapshotStore,
    source: SourceFeed,
    response: Response,
    significant: Significant = all_bytes,
) -> Recorded:
    """Store a fetched response unless it is what the URL already returned.

    "What it already returned" is judged on `significant(bytes)`, so a source can
    ignore parts of a page that change on every request. The bytes stored are
    always exactly what was served; when only insignificant parts differ, nothing
    new is stored and the existing snapshot stays current.
    """
    identity = response.request.identity
    sha256 = hashlib.sha256(response.content).hexdigest()

    current = session.scalars(
        select(RawSnapshot)
        .where(RawSnapshot.url == identity)
        .order_by(RawSnapshot.last_seen_at.desc(), RawSnapshot.id.desc())
        .limit(1)
    ).first()
    if current is not None and (
        current.content_sha256 == sha256
        or (
            significant is not all_bytes
            and _same_significant(store, current, response, significant)
        )
    ):
        _seen(session, current)
        return Recorded(current, changed=False)

    # The page went back to something already stored (A → B → A). The row exists and
    # cannot be duplicated; marking it seen makes it current again.
    previous = session.scalars(
        select(RawSnapshot).where(RawSnapshot.url == identity, RawSnapshot.content_sha256 == sha256)
    ).first()
    if previous is not None:
        _seen(session, previous)
        return Recorded(previous, changed=True)

    key = SnapshotStore.key_for(source.slug, sha256)
    store.put(key, response.content)  # bytes before the row: a row must never point at nothing
    snapshot = RawSnapshot(
        source_feed_id=source.id,
        url=identity,
        content_sha256=sha256,
        http_status=response.status,
        content_type=response.content_type,
        byte_length=len(response.content),
        storage_key=key,
    )
    session.add(snapshot)
    session.flush()
    return Recorded(snapshot, changed=True)


def _same_significant(
    store: SnapshotStore, current: RawSnapshot, response: Response, significant: Significant
) -> bool:
    try:
        stored = store.get(current.storage_key)
    except (OSError, CorruptSnapshot):
        return False  # cannot compare, so store the new bytes: never skip on doubt
    return significant(stored) == significant(response.content)


def _seen(session: Session, snapshot: RawSnapshot) -> None:
    # clock_timestamp, not now(): now() is frozen for the whole transaction, so two
    # fetches inside one run would otherwise look simultaneous.
    snapshot.last_seen_at = func.clock_timestamp()
    session.flush()
    session.refresh(snapshot, ["last_seen_at"])
