"""Writing chunks for normalised snapshots, and filling their embeddings.

Two steps, deliberately separate:

1. **Chunking** is cheap and cannot fail on a normalised snapshot. Every snapshot
   with text gets its chunks, once.
2. **Embedding** needs the model loaded (seconds, ~1.5 GB) and can fail if it has
   not been downloaded. Chunks without a vector from the current model are
   filled in batches, committed as they go, and picked up again by the next run
   if this one stops.

A chunk without a vector is still found by trigram search, and search reports
how many chunks in scope lacked one (app/retrieval/search.py), so an embedding
backlog shows up as incomplete retrieval rather than as silently worse results.

Both run after ingestion (`flask ingest run|due`) and on their own with
`flask ingest index`. Snapshots are content-addressed, so only changed documents
ever produce new chunks.
"""

from dataclasses import dataclass

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Chunk, RawSnapshot
from app.retrieval.chunker import chunk_spans
from app.retrieval.embedder import BATCH_SIZE, Embedder


@dataclass(frozen=True)
class IndexResult:
    snapshots_chunked: int
    chunks_written: int
    chunks_embedded: int


def chunk_snapshot(session: Session, snapshot: RawSnapshot) -> int:
    """Write this snapshot's chunks unless it has them. Returns how many were written."""
    if not snapshot.normalised_text:
        return 0
    if session.scalar(select(exists().where(Chunk.snapshot_id == snapshot.id))):
        return 0  # never rewritten: evidence rows may point at these chunks
    text = snapshot.normalised_text
    spans = chunk_spans(text)
    session.add_all(
        Chunk(
            snapshot_id=snapshot.id,
            ordinal=span.ordinal,
            char_start=span.start,
            char_end=span.end,
            text=text[span.start : span.end],
        )
        for span in spans
    )
    session.flush()
    return len(spans)


def unchunked_snapshots(session: Session, limit: int = 100, after_id: int = 0) -> list[RawSnapshot]:
    return list(
        session.scalars(
            select(RawSnapshot)
            .where(
                RawSnapshot.id > after_id,
                func.length(RawSnapshot.normalised_text) > 0,
                ~exists().where(Chunk.snapshot_id == RawSnapshot.id),
            )
            .order_by(RawSnapshot.id)
            .limit(limit)
        )
    )


def needs_embedding(embedder_name: str):
    """Chunks with no vector, or a vector from a model other than the current one."""
    return or_(Chunk.embedding.is_(None), Chunk.embedding_model != embedder_name)


def index_pending(sessions: sessionmaker[Session], embedder: Embedder) -> IndexResult:
    snapshots = chunks = 0
    with sessions() as session:
        # A cursor rather than "until none are left": text that is only whitespace
        # has no chunks, and would otherwise be picked up forever.
        last_id = 0
        while batch := unchunked_snapshots(session, after_id=last_id):
            last_id = batch[-1].id
            for snapshot in batch:
                written = chunk_snapshot(session, snapshot)
                chunks += written
                snapshots += bool(written)
            session.commit()

    embedded = 0
    with sessions() as session:
        # Loaded only when there is something to embed: most runs change nothing.
        while batch := list(
            session.scalars(
                select(Chunk)
                .where(needs_embedding(embedder.name))
                .order_by(Chunk.id)
                .limit(BATCH_SIZE * 4)
            )
        ):
            vectors = embedder.passages([chunk.text for chunk in batch])
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector
                chunk.embedding_model = embedder.name
            session.commit()
            embedded += len(batch)

    return IndexResult(snapshots, chunks, embedded)
