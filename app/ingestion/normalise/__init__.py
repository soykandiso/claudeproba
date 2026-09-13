"""Raw snapshot bytes → normalised_text, the string every citation indexes into.

Three properties matter more than anything else here:

1. **Faithful.** The text says what the document says. No de-hyphenation, no
   "fixing" quotes, no summarising. Inline markup joins without inserted spaces,
   so `202<span>3</span>` stays `2023` (docs/sources.md §6.3).
2. **Deterministic.** The same bytes and NORMALISER_VERSION always give the same
   string, so an offset computed today still points at the same characters.
3. **Written once.** A snapshot's normalised_text is never rewritten, even by a
   newer normaliser version, because evidence rows cite it by offset.

PDF pages are separated by a form feed (`\\f`), so the page a citation falls on is
`page_of(text, char_start)` with no extra column.
"""

import re
from dataclasses import dataclass

from app.models.enums import TextSource

# Bump when a change would alter the output for bytes already normalised. Only
# snapshots normalised after the bump use the new version; see property 3.
NORMALISER_VERSION = "2026-09-13.1"

PAGE_BREAK = "\f"


class NormaliseError(RuntimeError):
    """The document could not be turned into text. It goes to review, never dropped."""


class UnsupportedFormat(NormaliseError):
    pass


@dataclass(frozen=True)
class Normalised:
    text: str
    text_source: TextSource
    ocr_pages: tuple[int, ...] = ()
    ocr_mean_confidence: float | None = None
    review_reasons: tuple[str, ...] = ()
    ocr_engine: str | None = None  # e.g. "tesseract-5.3.0"; OCR output varies by version


@dataclass(frozen=True)
class Span:
    start: int
    end: int


# Latin letters that render identically to Cyrillic ones. Official documents mix
# them in by hand: the Economy call DOCX has "Mинистерството" and "зa", the IPARD
# notice "Aлтернативно" (docs/sources.md §6.3). One character to one character, so
# folding never moves an offset.
_LOOKALIKES = str.maketrans(
    {
        # Latin: Cyrillic (Macedonian alphabet only), written as escapes because the
        # whole point is that the two sides look the same.
        "a": "\u0430", "c": "\u0441", "e": "\u0435", "j": "\u0458", "o": "\u043e",
        "p": "\u0440", "s": "\u0455", "x": "\u0445", "y": "\u0443",
        "A": "\u0410", "B": "\u0412", "C": "\u0421", "E": "\u0415", "H": "\u041d",
        "J": "\u0408", "K": "\u041a", "M": "\u041c", "O": "\u041e", "P": "\u0420",
        "S": "\u0405", "T": "\u0422", "X": "\u0425",
    }
)  # fmt: skip


def fold_lookalikes(text: str) -> str:
    """Latin look-alike letters → Cyrillic. Same length as the input, always."""
    return text.translate(_LOOKALIKES)


def find_quote(text: str, quote: str, *, fold: bool = False) -> list[Span]:
    """Every occurrence of quote in text.

    Exact by default. With fold=True, Latin look-alikes are treated as their
    Cyrillic twins on both sides; the spans still index the original text, so
    `text[span.start:span.end]` is what the document actually says.
    """
    if not quote:
        return []
    haystack, needle = (fold_lookalikes(text), fold_lookalikes(quote)) if fold else (text, quote)
    spans, start = [], haystack.find(needle)
    while start != -1:
        spans.append(Span(start, start + len(needle)))
        start = haystack.find(needle, start + 1)
    return spans


def page_of(text: str, offset: int) -> int:
    """1-based page number of a character offset in a PDF's normalised text."""
    return text.count(PAGE_BREAK, 0, offset) + 1


def letters(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


def sniff(content: bytes, content_type: str | None) -> str:
    head = content[:2048]
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole"  # legacy .doc / .xls
    ctype = (content_type or "").lower()
    stripped = head.lstrip().lower()
    if (
        "html" in ctype
        or stripped.startswith((b"<!doctype html", b"<html"))
        or b"<body" in head.lower()
    ):
        return "html"
    if "json" in ctype or stripped[:1] in (b"{", b"["):
        return "json"
    if ctype.startswith("text/"):
        return "text"
    return "unknown"


_META_CHARSET = re.compile(rb"<meta[^>]+charset=[\"']?([\w-]+)", re.IGNORECASE)


def decode(content: bytes, content_type: str | None) -> str:
    """Header charset, then <meta> charset, then UTF-8, then windows-1251.

    windows-1251 is the legacy Cyrillic encoding still found on Macedonian
    government sites; guessing it only after UTF-8 fails keeps UTF-8 pages exact.
    """
    candidates = []
    if content_type and "charset=" in content_type.lower():
        candidates.append(content_type.lower().split("charset=")[1].split(";")[0].strip(" \"'"))
    if meta := _META_CHARSET.search(content[:4096]):
        candidates.append(meta.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "windows-1251"]
    for encoding in candidates:
        try:
            return content.decode(
                "utf-8-sig" if encoding.lower() in ("utf-8", "utf8") else encoding
            )
        except (UnicodeDecodeError, LookupError):
            continue
    raise NormaliseError("could not decode the document as text")


def normalise(
    content: bytes,
    content_type: str | None = None,
    *,
    ocr=None,
    html_root: str | None = None,
) -> Normalised:
    """Dispatch on what the bytes are, not on what the URL claims."""
    from app.ingestion.normalise import docx, html, pdf, text

    kind = sniff(content, content_type)
    if kind == "pdf":
        return pdf.normalise_pdf(content, ocr=ocr)
    if kind == "zip":
        return docx.normalise_docx(content)
    if kind == "html":
        return html.normalise_html(decode(content, content_type), root=html_root)
    if kind == "text":
        return Normalised(text.canonical(decode(content, content_type)), TextSource.NATIVE)
    if kind == "ole":
        raise UnsupportedFormat("legacy Word/Excel (.doc/.xls) is not supported; needs a human")
    if kind == "json":
        raise UnsupportedFormat(
            "JSON is source-specific; the source's fetcher must extract the text"
        )
    raise UnsupportedFormat(f"unrecognised document format (content-type {content_type!r})")
