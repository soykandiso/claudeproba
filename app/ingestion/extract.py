"""Normalised documents → CallExtraction, with every quote located in code.

The model reads a call's documents and returns facts with quotes. This module
never trusts where the model says a quote is: it finds each quote verbatim in
the snapshot's normalised_text and records the offsets itself. A quote that is
not there -- paraphrased, stitched across two lines, or copied across an
identity pseudonym the scrubber put in -- is a failed citation, and an
extraction with any failed citation goes to the review queue whole. Nothing is
silently dropped.

Matching folds Latin look-alike letters (docs/sources.md §6.3): the documents
mix them into Cyrillic words and a model copying "Aлтернативно" will write it
all-Cyrillic. Folding is one character for one character, so the offsets and the
stored quote are still exactly what the document says. Whether verification of
applicant evidence folds too is decided separately (P2 s29).

This module extracts; it does not write calls or criteria. The fetcher that
owns a call does that (P1 s11), and only a human publishes (P1 s15).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai.gateway import Gateway
from app.ai.schemas import CallExtraction
from app.ingestion.normalise import find_quote
from app.models import RawSnapshot, ReviewQueueItem
from app.models.enums import ReviewKind

TASK = "extract_call"


@dataclass(frozen=True)
class Document:
    snapshot_id: int
    url: str
    text: str

    @classmethod
    def from_snapshot(cls, snapshot: RawSnapshot) -> "Document":
        if not snapshot.normalised_text:
            raise ValueError(f"snapshot {snapshot.id} has no normalised text to extract from")
        return cls(snapshot.id, snapshot.url, snapshot.normalised_text)


@dataclass(frozen=True)
class Citation:
    """(snapshot_id, char_start, char_end) plus what the document says there."""

    snapshot_id: int
    url: str
    char_start: int
    char_end: int
    source_quote: str  # text[char_start:char_end], which may differ from the model's by look-alikes
    occurrences: int  # >1 means the same words appear elsewhere too; the first is cited


@dataclass(frozen=True)
class CitationFailure:
    path: str
    document: int
    quote: str
    reason: str


@dataclass(frozen=True)
class Extraction:
    output: CallExtraction
    citations: dict[str, Citation]
    failures: list[CitationFailure]
    model_call_id: int
    cache_hit: bool
    review_item_id: int | None = None
    documents: list[Document] = field(default_factory=list, repr=False)

    @property
    def ok(self) -> bool:
        return not self.failures


def render_documents(documents: Sequence[Document]) -> str:
    return "\n\n".join(
        f'<document index="{index}" url="{doc.url}">\n{doc.text}\n</document>'
        for index, doc in enumerate(documents, start=1)
    )


def locate_citations(
    output: CallExtraction, documents: Sequence[Document]
) -> tuple[dict[str, Citation], list[CitationFailure]]:
    citations: dict[str, Citation] = {}
    failures: list[CitationFailure] = []
    for path, item in output.quoted():
        if item.document > len(documents):
            failures.append(CitationFailure(path, item.document, item.quote, "no such document"))
            continue
        doc = documents[item.document - 1]
        spans = find_quote(doc.text, item.quote, fold=True)
        if not spans:
            failures.append(
                CitationFailure(path, item.document, item.quote, "quote not found verbatim")
            )
            continue
        first = spans[0]
        citations[path] = Citation(
            snapshot_id=doc.snapshot_id,
            url=doc.url,
            char_start=first.start,
            char_end=first.end,
            source_quote=doc.text[first.start : first.end],
            occurrences=len(spans),
        )
    return citations, failures


def extract_call(
    gateway: Gateway,
    session_factory: Callable[[], Session],
    documents: Sequence[Document],
    *,
    call_id=None,
) -> Extraction:
    """Run extraction over one call's documents.

    Raises InvalidModelOutput when the reply fails the schema twice; the gateway
    has already queued it for review. Returns an Extraction otherwise, with
    review_item_id set when any citation could not be located.
    """
    if not documents:
        raise ValueError("extraction needs at least one document")
    documents = list(documents)

    result = gateway.run(
        TASK,
        variables={"documents": render_documents(documents)},
        response_model=CallExtraction,
        on_invalid=ReviewKind.EXTRACTION,
        call_id=call_id,
    )
    citations, failures = locate_citations(result.output, documents)

    review_item_id = None
    if failures:
        review_item_id = _send_to_review(session_factory, result, documents, failures, call_id)
    return Extraction(
        output=result.output,
        citations=citations,
        failures=failures,
        model_call_id=result.model_call_id,
        cache_hit=result.cache_hit,
        review_item_id=review_item_id,
        documents=documents,
    )


def _send_to_review(session_factory, result, documents, failures, call_id) -> int:
    # Its own transaction, like the gateway's audit rows: the record that a
    # citation failed must survive a caller that rolls back.
    with session_factory() as session:
        item = ReviewQueueItem(
            kind=ReviewKind.EXTRACTION,
            reason=(
                f"{TASK}: {len(failures)} of {sum(1 for _ in result.output.quoted())} "
                "quotes not found verbatim in the documents"
            ),
            payload={
                "stage": "extract",
                "snapshot_ids": [doc.snapshot_id for doc in documents],
                "model_call_id": result.model_call_id,
                "failures": [
                    {"path": f.path, "document": f.document, "quote": f.quote, "reason": f.reason}
                    for f in failures
                ],
                "extraction": result.output.model_dump(mode="json"),
            },
            call_id=call_id,
        )
        session.add(item)
        session.commit()
        return item.id
