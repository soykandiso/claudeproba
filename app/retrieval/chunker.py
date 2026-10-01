"""normalised_text → overlapping chunks that index back into it exactly.

A chunk is a span, not a copy: `text[start:end]` is the chunk, always. The
verification pass checks a model's quote verbatim against the chunk it cites
(docs/matching.md §5), so a chunker that trimmed, joined or "cleaned" text would
turn true quotes into rejected ones.

How text is cut:

1. Units are lines (runs between `\\n` and `\\f`), with surrounding spaces left
   out. A line longer than MAX_CHARS is cut after a sentence end, else at a
   space, else hard at MAX_CHARS.
2. Units are packed in order while the chunk stays within MAX_CHARS.
3. The next chunk starts with the trailing units of the previous one that fit in
   OVERLAP_CHARS, so a clause that wraps across two lines at a chunk boundary
   (IPARD PDFs wrap mid-sentence) is whole in at least one chunk.

Sizes were chosen on the three extraction fixtures (P1 s12): 900 characters kept
every hand-written paraphrase query's clause in the top 3 with the chosen model,
and Macedonian runs at about 4 characters per token, so a chunk is ~230 tokens,
well inside the model's 512. Text that tokenises far worse (OCR noise) is cut at
512 tokens by the model; its trigram match still sees the whole chunk.

Changing these numbers affects snapshots chunked afterwards only: existing chunks
are never rewritten (app/retrieval/__init__.py).
"""

import re
from dataclasses import dataclass

MAX_CHARS = 900
OVERLAP_CHARS = 200

_LINE = re.compile(r"[^\n\f]+")
# A cut after these keeps a sentence or list item whole.
_SENTENCE_END = re.compile(r"[.;:!?](?=\s)")


@dataclass(frozen=True)
class Span:
    ordinal: int
    start: int
    end: int


def chunk_spans(text: str) -> list[Span]:
    units = [unit for line in _LINE.finditer(text) for unit in _split_line(text, *line.span())]
    spans: list[Span] = []
    i = 0
    while i < len(units):
        start = units[i][0]
        j = i
        while j + 1 < len(units) and units[j + 1][1] - start <= MAX_CHARS:
            j += 1
        spans.append(Span(len(spans), start, units[j][1]))
        if j + 1 == len(units):
            break
        # Back up over trailing units that fit in the overlap, but always move forward.
        k = j + 1
        while k - 1 > i and units[j][1] - units[k - 1][0] <= OVERLAP_CHARS:
            k -= 1
        i = k
    return spans


def _split_line(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """One line as (start, end) units of at most MAX_CHARS, spaces trimmed."""
    units = []
    while True:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start == end:
            return units
        if end - start <= MAX_CHARS:
            units.append((start, end))
            return units
        cut = _cut_point(text, start, start + MAX_CHARS)
        units.append((start, cut))
        start = cut


def _cut_point(text: str, start: int, limit: int) -> int:
    window = text[start:limit]
    # Only cuts in the second half: a cut near the start would leave a crumb.
    ends = [m.end() for m in _SENTENCE_END.finditer(window) if m.end() > len(window) // 2]
    if ends:
        return start + ends[-1]
    space = window.rfind(" ", len(window) // 2)
    if space > 0:
        return start + space
    return limit
