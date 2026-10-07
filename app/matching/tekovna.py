"""Filling the intake from a тековна состојба of the Central Registry (CRM).

A company owner has this PDF, or can download it from crm.com.mk; uploading it fills four of
the five required answers. What it does not say (the headcount, and everything optional) is
completed by hand, as before.

**Only the shape of the company is taken.** A тековна carries the name, ЕМБС, ЕДБ, the
seat's street, the owners' and managers' names and addresses, an e-mail and the capital.
This module reads past all of it and returns four things: the legal form, the municipality
of the seat, the founding year and the main activity. The file is read in memory, never
written to disk, never stored and never sent anywhere; no model sees it (CLAUDE.md
invariant 4). The intake's data minimisation (brief §3.3) is unchanged: a profile still
holds no name and no identifier.

**Reading it is exact, not OCR.** CRM renders the document with Microsoft Reporting
Services, which embeds Calibri as a Type0 font with `Identity-H` encoding and no
`ToUnicode` table, so a PDF reader extracts glyph numbers instead of letters («ʪʽʽʫʸ» for
«ДООЕЛ»). The embedded font keeps its own character map and Calibri's glyph numbers, so
each glyph is mapped back to its letter through that map (`_glyph_letters`). A font that
has a `ToUnicode` table is read as it is.

**The activity is never guessed silently.** CRM writes the main activity as «80.010», a
form the classification does not use (НКД writes 80.10). When the code does not exist as
written, its two readings (80.01, 80.10) are tried; one that exists is used and marked for
the user to check, and with none or both, only the division (80) is filled, which is
certain. A coarser activity can only make a condition «Потребна е проверка»; a wrong one
could exclude the company from a call it qualifies for (invariant 3).
"""

import io
import re
from dataclasses import dataclass, field

import pypdf
from fontTools.ttLib import TTFont

from app.matching import reference

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 20

# «Вид на субјект на упис» → the intake's legal form. Forms the intake does not offer
# (ЈТД, КД, …) are left for the user to choose rather than mapped to a neighbour.
FORMS = {
    "ДООЕЛ": "dooel",
    "ДОО": "doo",
    "АД": "ad",
    "ТП": "tp",
    "ТРГОВЕЦ ПОЕДИНЕЦ": "tp",
    "ЗДРУЖЕНИЕ": "ngo",
    "ЗДРУЖЕНИЕ НА ГРАЃАНИ": "ngo",
}

# CRM's PDF writes its spaces as non-breaking and its hyphens as U+2010: one of each, so a
# label matches as it is printed.
_PLAIN = {**dict.fromkeys(map(ord, "‐‑‒–—−"), "-"), **dict.fromkeys(map(ord, "   "), " ")}


class NotATekovna(ValueError):
    """The file is not a тековна состојба this module can read; the form is filled by hand."""


@dataclass(frozen=True)
class Reading:
    """What the тековна says, in the intake's own values; None where it says nothing usable."""

    entity: str | None = None
    municipality: str | None = None
    founded: str | None = None
    nace: str | None = None
    # How sure the activity is: "exact", "check" (one reading of CRM's code), "division"
    # (only the first two digits are certain), or None.
    nace_certainty: str | None = None
    # The activity as CRM writes it, shown to the user beside what was filled.
    activity_as_written: str | None = None
    unread: list[str] = field(default_factory=list)

    def answers(self) -> dict[str, str]:
        found = {
            "entity": self.entity,
            "municipality": self.municipality,
            "founded": self.founded,
            "nace": self.nace,
        }
        return {k: v for k, v in found.items() if v}


# ------------------------------------------------------------------ the text


def _glyph_letters(font: dict) -> dict[int, str] | None:
    """Glyph number → letter, for a Type0 font that has no ToUnicode table."""
    if font.get("/Subtype") != "/Type0" or "/ToUnicode" in font:
        return None
    descriptor = font["/DescendantFonts"][0].get_object()["/FontDescriptor"].get_object()
    if "/FontFile2" not in descriptor:
        return None
    try:
        embedded = TTFont(io.BytesIO(descriptor["/FontFile2"].get_object().get_data()))
        order = {name: number for number, name in enumerate(embedded.getGlyphOrder())}
        return {order[name]: chr(code) for code, name in embedded.getBestCmap().items()}
    except Exception:  # noqa: BLE001 -- a font we cannot read is a document we cannot read
        return None


def decode(pdf: bytes) -> str:
    """The document's text, each font read the way it was written."""
    if len(pdf) > MAX_BYTES:
        raise NotATekovna("too large")
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf))
        if len(reader.pages) > MAX_PAGES:
            raise NotATekovna("too many pages")
        pages = []
        for page in reader.pages:
            letters: dict[int, dict | None] = {}
            parts: list[str] = []

            def visit(text, _cm, _tm, font, _size, letters=letters, parts=parts):
                if not text:
                    return
                if font is not None and id(font) not in letters:
                    letters[id(font)] = _glyph_letters(font)
                table = letters.get(id(font)) if font is not None else None
                parts.append("".join(table.get(ord(c), c) for c in text) if table else text)

            page.extract_text(visitor_text=visit)
            pages.append("".join(parts))
    except NotATekovna:
        raise
    except Exception as error:  # noqa: BLE001 -- not a PDF, or a broken one
        raise NotATekovna("unreadable") from error
    return "\n".join(pages).translate(_PLAIN)


# ------------------------------------------------------------------ the four answers


def _value(lines: list[str], label: str, first: bool = False) -> str | None:
    """The text after a label line, up to the next label (a line ending in a colon); with
    `first`, its first line only, for a value a heading may follow without a gap."""
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(label.lower()):
            rest = line.strip()[len(label) :].strip()
            value = [rest] if rest else []
            for following in lines[i + 1 :]:
                stripped = following.strip()
                if not stripped or stripped.endswith(":"):
                    break
                value.append(stripped)
            if first:
                value = value[:1]
            return " ".join(value).strip() or None
    return None


def _municipality(seat: str | None) -> str | None:
    """The seat's municipality: CRM ends the address with it («…СКОПЈЕ - ЧАИР, ЧАИР»)."""
    if not seat:
        return None
    candidates = [seat.rsplit(",", 1)[-1]]
    candidates += [part.split("-")[-1] for part in seat.split(",")]
    for candidate in candidates:
        found = reference.resolve_municipality(candidate.strip())
        if found:
            return found.code
    return None


def _activity(written: str | None) -> tuple[str | None, str | None]:
    """(code, certainty) for CRM's main activity; see the module's note on «80.010»."""
    if not written:
        return None, None
    match = re.match(r"\s*(\d{2})\.(\d{2,3})", written)
    if not match:
        return None, None
    division, digits = match.groups()
    exact = reference.resolve_nace(f"{division}.{digits}")
    if exact:
        return exact.code, "exact"
    readings = {f"{division}.{digits[:2]}", f"{division}.{digits[-2:]}"}
    found = [code for code in sorted(readings) if reference.resolve_nace(code)]
    if len(found) == 1:
        return found[0], "check"
    if reference.resolve_nace(division):
        return division, "division"
    return None, None


def read(pdf: bytes) -> Reading:
    """The four answers a тековна gives. Raises NotATekovna for anything else."""
    text = decode(pdf)
    squeezed = re.sub(r"\s+", "", text).upper()
    if "ТЕКОВНАСОСТОЈБА" not in squeezed or "CRM.COM.MK" not in squeezed:
        raise NotATekovna("not a тековна состојба")
    lines = text.splitlines()

    form = (_value(lines, "Вид на субјект на упис:") or "").upper()
    founded = re.search(r"\d{1,2}\.\d{1,2}\.(\d{4})", _value(lines, "Датум на основање:") or "")
    written = _value(lines, "Главна приходна шифра:", first=True)
    nace, certainty = _activity(written)
    reading = Reading(
        entity=FORMS.get(form.strip()),
        municipality=_municipality(_value(lines, "Седиште:")),
        founded=founded.group(1) if founded else None,
        nace=nace,
        nace_certainty=certainty,
        activity_as_written=written,
    )
    unread = [
        key for key in ("entity", "municipality", "founded", "nace") if not getattr(reading, key)
    ]
    return Reading(**{**reading.__dict__, "unread": unread})
