"""Whitespace and Unicode canonicalisation shared by every format."""

import re
import unicodedata

from app.ingestion.normalise import PAGE_BREAK

# Soft hyphen, zero-width space/joiners, word joiner, BOM: invisible, and they
# would make a quote copied from the rendered document fail to match.
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"), None)
_SPACES = re.compile("[ \t\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")


def canonical(text: str) -> str:
    """NFC, invisible characters removed, spaces collapsed per line, blank lines collapsed.

    NFC matters for Macedonian: ќ and ѓ sometimes arrive decomposed (к + U+0301)
    from PDFs, and a decomposed ќ never equals the composed one a model types.
    """
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(PAGE_BREAK, "\n")
    out: list[str] = []
    for line in text.split("\n"):
        line = _SPACES.sub(" ", line).strip()
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip("\n")


def join_pages(pages: list[str]) -> str:
    return PAGE_BREAK.join(canonical(page) for page in pages)
