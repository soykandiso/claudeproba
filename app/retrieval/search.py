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
  measurement and the threshold used the same queries; P2 s30 retunes on a
  larger set.

Reciprocal rank fusion: score = Σ 1 / (RRF_K + rank) over the rankings a chunk
appears in. Ranks, not raw scores, because cosine distances and trigram
similarities are not on the same scale.

Both rankings are exact scans over the chunks in scope -- tens of rows for a
call. There is deliberately no vector index on chunk.embedding: an approximate
index scanned under a WHERE filter can return fewer rows than asked for, which
here would mean a missing clause and nobody told.

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
) -> Retrieval:
    in_scope = Chunk.snapshot_id.in_(snapshot_ids)

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
    best = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:k]
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
                score=scores[chunk_id],
                vector_rank=vector_rank.get(chunk_id),
                trigram_rank=trigram_rank.get(chunk_id),
            )
            for chunk_id in best
        ],
        unembedded=unembedded,
        unindexed_snapshots=len(set(snapshot_ids) - chunked),
    )
