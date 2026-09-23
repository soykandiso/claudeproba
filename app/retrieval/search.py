"""Hybrid retrieval over the documents of one call (docs/matching.md §5).

Two rankings of the same chunks, fused:

- **vector**: cosine distance between the query's embedding and each chunk's.
  Finds a clause worded differently from the question.
- **trigram**: pg_trgm `word_similarity(query, chunk.text)`, the best match of
  the query against any stretch of the chunk. Finds exact codes, amounts and
  dates ("725930 00", "11.340.000"), which embeddings blur, and works for a
  chunk whose vector is missing. PostgreSQL has no Macedonian full-text
  dictionary, which is why this is trigrams and not tsvector.

  Only chunks at or above TRIGRAM_MIN_SIMILARITY take part. Below it the score
  is noise -- Macedonian function words and endings share trigrams with every
  chunk -- and letting noise vote in the fusion pushed clauses the vectors had
  ranked first down to 4th and 11th. Measured on 46 queries over the three
  extraction fixtures (P1 s12): chunks that really contain the query's words
  scored 0.71-1.0, the best unrelated chunk for a paraphrased question at most
  0.54. 0.6 is also pg_trgm's own default word_similarity_threshold. The
  measurement and the threshold used the same queries. P2 s30 did not retune
  it: stage 3's query became the criterion's verbatim quote, which scores
  about 1.0 against its own chunk, so the threshold now matters only for
  paraphrased questions, and there is still no larger set of those to tune on.

Reciprocal rank fusion: score = Σ 1 / (RRF_K + rank) over the rankings a chunk
appears in. Ranks, not raw scores, because cosine distances and trigram
similarities are not on the same scale.

Both rankings are exact scans over the chunks in scope -- tens of rows for a
call. There is deliberately no vector index on chunk.embedding: an approximate
index scanned under a WHERE filter can return fewer rows than asked for, which
here would mean a missing clause and nobody told.

**A cited span can be pinned** (P2 s30). A criterion already says where its words
are -- (snapshot_id, quote_start, quote_end), checked verbatim when it was
approved -- so a caller that has that address passes it and the chunk holding it
comes first, whatever the rankings think. Searching for a clause whose location
is on record would only be a way to lose it: a call's long guideline repeats a
standard clause under every measure, and the fused rankings may prefer another
copy. The pin applies only when the cited snapshot is one of the documents in
scope; a criterion extracted from an older version of a document cites text the
source no longer shows, and then the search decides alone.

Retrieval does not decide anything. A caller that gets an incomplete result, or
no passage containing what it needs, ends in needs_verification (CLAUDE.md
invariant 3).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CallDocument, Chunk, RawSnapshot
from app.retrieval.embedder import Embedder
from app.retrieval.index import needs_embedding

RRF_K = 60
TRIGRAM_MIN_SIMILARITY = 0.6
# Each ranking contributes this many candidates to the fusion.
CANDIDATES = 20


@dataclass(frozen=True)
class Passage:
    chunk_id: int
    snapshot_id: int
    char_start: int
    char_end: int
    text: str
    score: float
    vector_rank: int | None
    trigram_rank: int | None
    # Placed first because a caller named its span, not because it ranked.
    pinned: bool = False


@dataclass(frozen=True)
class Retrieval:
    passages: list[Passage]
    # Chunks in scope that have no vector from the current model. Non-zero means
    # the vector ranking saw only part of the documents.
    unembedded: int
    # Snapshots in scope that have no chunks at all (not normalised, or not yet
    # indexed). Non-zero means some text was not searched.
    unindexed_snapshots: int

    @property
    def complete(self) -> bool:
        return self.unembedded == 0 and self.unindexed_snapshots == 0


def call_snapshot_ids(session: Session, call_id: uuid.UUID) -> list[int]:
    """The current version of each document of a call.

    call_document keeps every version a call has had, because approved criteria
    and delivered reports cite old snapshots. Retrieval wants what the source
    says now: for each document URL, the snapshot seen most recently.
    """
    ranked = (
        select(
            RawSnapshot.id,
            func.row_number()
            .over(
                partition_by=RawSnapshot.url,
                order_by=(RawSnapshot.last_seen_at.desc(), RawSnapshot.id.desc()),
            )
            .label("recency"),
        )
        .join(CallDocument, CallDocument.snapshot_id == RawSnapshot.id)
        .where(CallDocument.call_id == call_id)
        .subquery()
    )
    return list(session.scalars(select(ranked.c.id).where(ranked.c.recency == 1).order_by("id")))


def hybrid_retrieve(
    session: Session,
    embedder: Embedder,
    snapshot_ids: list[int],
    query: str,
    *,
    k: int = 6,
    pin: tuple[int, int, int] | None = None,
) -> Retrieval:
    """The k best chunks for `query` among `snapshot_ids`.

    `pin` is (snapshot_id, char_start, char_end) of a span the caller already
    knows is relevant: the chunks holding it come first (see the module docstring).
    """
    in_scope = Chunk.snapshot_id.in_(snapshot_ids)
    pinned = _pinned(session, pin) if pin and pin[0] in snapshot_ids else []

    vector_ids = list(
        session.scalars(
            select(Chunk.id)
            .where(in_scope, Chunk.embedding_model == embedder.name)
            .order_by(Chunk.embedding.cosine_distance(embedder.query(query)), Chunk.id)
            .limit(CANDIDATES)
        )
    )
    similarity = func.word_similarity(query, Chunk.text)
    trigram_ids = list(
        session.scalars(
            select(Chunk.id)
            .where(in_scope, similarity >= TRIGRAM_MIN_SIMILARITY)
            .order_by(similarity.desc(), Chunk.id)
            .limit(CANDIDATES)
        )
    )

    vector_rank = {chunk_id: rank for rank, chunk_id in enumerate(vector_ids, 1)}
    trigram_rank = {chunk_id: rank for rank, chunk_id in enumerate(trigram_ids, 1)}
    scores = {
        chunk_id: sum(1 / (RRF_K + ranks[chunk_id]) for ranks in (vector_rank, trigram_rank)
                      if chunk_id in ranks)
        for chunk_id in vector_rank | trigram_rank
    }  # fmt: skip
    ranked = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    best = (pinned + [chunk_id for chunk_id in ranked if chunk_id not in pinned])[:k]
    chunks = {c.id: c for c in session.scalars(select(Chunk).where(Chunk.id.in_(best)))}

    unembedded = session.scalar(
        select(func.count()).select_from(Chunk).where(in_scope, needs_embedding(embedder.name))
    )
    chunked = set(session.scalars(select(Chunk.snapshot_id.distinct()).where(in_scope)))

    return Retrieval(
        passages=[
            Passage(
                chunk_id=chunk_id,
                snapshot_id=chunks[chunk_id].snapshot_id,
                char_start=chunks[chunk_id].char_start,
                char_end=chunks[chunk_id].char_end,
                text=chunks[chunk_id].text,
                score=scores.get(chunk_id, 0.0),
                vector_rank=vector_rank.get(chunk_id),
                trigram_rank=trigram_rank.get(chunk_id),
                pinned=chunk_id in pinned,
            )
            for chunk_id in best
        ],
        unembedded=unembedded,
        unindexed_snapshots=len(set(snapshot_ids) - chunked),
    )


def _pinned(session: Session, pin: tuple[int, int, int]) -> list[int]:
    """The chunk that holds the whole span, else every chunk that overlaps it.

    The chunker's overlap exists so that a clause is whole in at least one chunk,
    and then one is enough. A span longer than the overlap can still straddle a
    boundary; then its pieces come in document order, and the model sees all of it.
    """
    snapshot_id, start, end = pin
    of_snapshot = Chunk.snapshot_id == snapshot_id
    whole = session.scalar(
        select(Chunk.id)
        .where(of_snapshot, Chunk.char_start <= start, Chunk.char_end >= end)
        .order_by(Chunk.ordinal)
        .limit(1)
    )
    if whole is not None:
        return [whole]
    return list(
        session.scalars(
            select(Chunk.id)
            .where(of_snapshot, Chunk.char_start < end, Chunk.char_end > start)
            .order_by(Chunk.ordinal)
        )
    )
