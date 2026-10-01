"""The paid report as a PDF (roadmap P2 s35): an approved draft, set in the project's own fonts.

`app/reports/compose.py` drafts, `app/review/report.py` is where a person approves,
and this module is the last step before a customer — so it checks again rather than
trusting that the steps before it did:

1. **Only an approved or edited `report` item is rendered.** A pending, rejected or
   blocked draft has no path to paper.
2. **`compose.blockers()` runs again** over the draft as it will be printed
   (`report.draft_of`): the lint and citation completeness against the stored text.
   Approval checked the same thing, but the stored text could have moved since, and
   a quote that no longer resolves must not be printed as if it did (invariant 2).
3. **The whole printed text is linted** — not only the model's prose, as compose
   does, but this template's own words too. Quotes and call titles are left out, for
   compose's reason: they are the institution's words.

**Cyrillic that is right on the VPS, not on this laptop.** The acceptance is "MK
renders correctly using fonts actually installed on the VPS", and the slim image has
almost none. So the PDF uses **only the woff2 files this repository ships**
(`app/web/static/fonts/`, the same ones the site serves), and two checks make that a
guarantee rather than a hope:

- **before rendering**, every character of the text must be in one of those fonts'
  character maps. A character they cannot draw would otherwise be drawn by whatever
  font the machine happens to have — or by none — and nothing would say so;
- **after rendering**, every font embedded in the PDF must be one of ours. That
  catches what the first check cannot: a CSS rule asking for a family we do not
  ship (the site's monospace is a system font, so the PDF sets identifiers in Fira
  Sans with tabular figures instead).

Either failure raises `RenderRefused` and produces no PDF. A report is sent late
before it is sent with a letter missing.

**One font file per weight, merged here.** The site ships each face as two subsets,
Latin and Cyrillic, that share one internal name and are chosen by `unicode-range`.
WeasyPrint 70 embeds both under that one name and mixes their glyph numbers: the
first render (30.09.2026) had right Cyrillic and wrong digits, punctuation and Latin
— while its extracted text was perfect, which is why the tests compare pixels too.
So `pdf_fonts()` merges each pair into one TrueType file with fontTools, once per
process, from the same woff2 files the site serves; the two can never drift apart.
The PDF takes only the token *values* from `tokens.css` (its `:root` block), never
its `@font-face` rules.

**A deadline is a date, never "three days left".** The site says the days in words
under 14 (design system), but a PDF is read days after it was made, and a relative
phrase on paper goes wrong silently. The date carries `--seal` as everywhere else.

Nothing is stored here: the draft is stored, the template is versioned
(`RENDERER_VERSION`, written into the PDF's metadata), so the same PDF can be made
again. Where a delivered PDF is kept is delivery's decision (P4 s53).
"""

import datetime as dt
import re
import tempfile
from dataclasses import dataclass
from functools import cache
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

import jinja2
import pypdf
from fontTools.ttLib import TTFont
from markupsafe import Markup
from sqlalchemy.orm import Session

from app.models import ReviewQueueItem
from app.models.enums import ReviewKind, ReviewState, Verdict
from app.reports import compose
from app.reports.lint import find_banned
from app.web.format import CRITERION_LABELS, VERDICT_LABELS, mkdate

RENDERER_VERSION = "2026-09-30.1"

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
STATIC = HERE.parent / "web" / "static"
FONTS = STATIC / "fonts"
# Our families as they appear in an embedded font's name: "ABCDEF+Fira-Sans".
OUR_FAMILIES = ("Source-Serif-4", "Fira-Sans")

RENDERABLE = (ReviewState.APPROVED, ReviewState.EDITED)


class RenderRefused(ValueError):
    """The report cannot be printed as it stands. The message is for the operator."""


@dataclass
class Rendered:
    pdf: bytes
    pages: int
    fonts: list[str]


# ------------------------------------------------------------------ the checks


# (family, weight, the subsets that make it): what the site ships, as the PDF needs it.
FACES = (
    ("Fira Sans", 400, "fira-sans-{}-400-normal.woff2"),
    ("Fira Sans", 500, "fira-sans-{}-500-normal.woff2"),
    ("Source Serif 4", 400, "source-serif-4-{}-400-normal.woff2"),
    ("Source Serif 4", 600, "source-serif-4-{}-600-normal.woff2"),
)
SUBSETS = ("latin", "cyrillic")


@cache
def pdf_fonts() -> Path:
    """A directory holding one merged TrueType file per face, made once per process."""
    from fontTools.merge import Merger

    out = Path(tempfile.mkdtemp(prefix="report-fonts-"))
    for _, _, pattern in FACES:
        parts = []
        for subset in SUBSETS:
            font = TTFont(FONTS / pattern.format(subset))
            font.flavor = None  # woff2 in, plain TrueType out: what Merger reads
            path = out / pattern.format(subset).replace(".woff2", ".ttf")
            font.save(path)
            parts.append(str(path))
        merged = Merger().merge(parts)
        merged.save(out / pattern.format("all").replace(".woff2", ".ttf"))
    return out


def font_faces() -> str:
    """`@font-face` rules over the merged files, in place of tokens.css's split ones."""
    fonts = pdf_fonts()
    return "\n".join(
        f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
        f'src: url("{(fonts / pattern.format("all").replace(".woff2", ".ttf")).as_uri()}"); }}'
        for family, weight, pattern in FACES
    )


def token_values() -> str:
    """tokens.css's `:root` block alone: the values, without the site's font files."""
    css = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    match = re.search(r"^:root\s*\{.*?^\}", css, re.MULTILINE | re.DOTALL)
    if match is None:
        raise RenderRefused("tokens.css has no :root block to take the report's values from")
    return match.group(0)


@cache
def covered_characters() -> frozenset[str]:
    """Every character the shipped fonts can draw: the union of their character maps."""
    chars: set[str] = set()
    for path in sorted(FONTS.glob("*.woff2")):
        chars |= {chr(code) for code in TTFont(path).getBestCmap()}
    return frozenset(chars)


def uncovered(text: str) -> list[str]:
    """Characters the shipped fonts cannot draw. Line breaks and tabs are layout, not glyphs."""
    missing = set(text) - covered_characters() - {"\n", "\r", "\t"}
    return sorted(missing)


def embedded_fonts(pdf: bytes) -> list[str]:
    """The base names of the fonts a PDF embeds, subset prefix included."""
    names = set()
    for page in pypdf.PdfReader(BytesIO(pdf)).pages:
        fonts = (page.get("/Resources") or {}).get("/Font") or {}
        for ref in fonts.values():
            names.add(str(ref.get_object()["/BaseFont"]).lstrip("/"))
    return sorted(names)


def _ours(name: str) -> bool:
    family = name.split("+", 1)[-1]
    return any(family.startswith(f) for f in OUR_FAMILIES)


# ------------------------------------------------------------------ the document


def _instant(value: str | None) -> str | None:
    # Deadlines are stored as instants; the day is Skopje's (app/web/format.py).
    return mkdate(dt.datetime.fromisoformat(value)) if value else None


def _host(url: str | None) -> str:
    return url.split("/")[2] if url and "//" in url else (url or "")


@cache
def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["mkdate"] = mkdate
    env.filters["instant"] = _instant
    env.filters["host"] = _host
    env.globals["verdict_labels"] = {v.value: label for v, label in VERDICT_LABELS.items()}
    env.globals["criterion_labels"] = {v.value: label for v, label in CRITERION_LABELS.items()}
    env.globals["decided_by"] = compose.DECIDED_BY_MK
    return env


def html_of(draft: dict, *, issued: dt.date, reference: str) -> str:
    """The report as HTML, for WeasyPrint and for tests that read what it says."""
    return (
        _environment()
        .get_template("report.html")
        .render(
            draft=draft,
            issued=issued,
            reference=reference,
            font_faces=Markup(font_faces()),
            tokens=Markup(token_values()),
            report_css=Markup((TEMPLATES / "report.css").as_uri()),
            renderer_version=RENDERER_VERSION,
            not_eligible=Verdict.NOT_ELIGIBLE.value,
        )
    )


class _Text(HTMLParser):
    """The text a reader sees; with `theirs=False`, minus what is marked `data-theirs`."""

    HIDDEN = ("head", "style", "title")
    VOID = ("area", "base", "br", "col", "hr", "img", "input", "link", "meta", "wbr")

    def __init__(self, *, theirs: bool):
        super().__init__()
        self.theirs, self.parts, self.skip = theirs, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return  # never closed, so never counted
        if self.skip or tag in self.HIDDEN or (not self.theirs and ("data-theirs", None) in attrs):
            self.skip += 1

    def handle_startendtag(self, tag, attrs):
        pass  # void elements (<meta>, <link>) never open a skip they would not close

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _text(html: str, *, theirs: bool) -> str:
    parser = _Text(theirs=theirs)
    parser.feed(html)
    return " ".join(parser.parts)


def own_voice(html: str) -> str:
    """The printed text minus the institution's own words (quotes and call titles)."""
    return _text(html, theirs=False)


def visible_text(html: str) -> str:
    """Everything printed, the institution's words included: what the fonts must draw."""
    return _text(html, theirs=True)


def render(session: Session, item: ReviewQueueItem, *, issued: dt.date | None = None) -> Rendered:
    """The approved report as PDF bytes. Raises RenderRefused, never prints a doubt."""
    from app.review import report  # the review module imports compose; keep this one leaf-like

    if item.kind != ReviewKind.REPORT:
        raise RenderRefused(f"item {item.id} is not a report")
    if item.state not in RENDERABLE:
        raise RenderRefused(f"report {item.id} is {item.state}, not approved")
    draft = report.draft_of(item)
    if draft.get("version") != compose.DRAFT_VERSION:
        raise RenderRefused(f"report {item.id}: draft version {draft.get('version')!r} unknown")
    problems = compose.blockers(session, item)
    if problems:
        details = "; ".join(f"{p['check']} at {p['where']}: {p['detail']}" for p in problems)
        raise RenderRefused(f"report {item.id} no longer passes its checks: {details}")

    html = html_of(draft, issued=issued or dt.date.today(), reference=f"И-{item.id}")
    banned = find_banned(own_voice(html))
    if banned:
        raise RenderRefused(f"report {item.id}: banned phrase in the printed text: {banned}")
    missing = uncovered(visible_text(html))
    if missing:
        codes = ", ".join(f"U+{ord(c):04X}" for c in missing)
        raise RenderRefused(f"report {item.id}: the shipped fonts cannot draw {codes}")

    pdf = _pdf(html)
    fonts = embedded_fonts(pdf)
    strangers = [f for f in fonts if not _ours(f)]
    if strangers:
        raise RenderRefused(f"report {item.id}: a font we do not ship was used: {strangers}")
    return Rendered(pdf=pdf, pages=len(pypdf.PdfReader(BytesIO(pdf)).pages), fonts=fonts)


def _pdf(html: str) -> bytes:
    # Imported here: WeasyPrint loads Pango at import, and only this path needs it.
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration

    return HTML(string=html, base_url=str(STATIC / "css") + "/").write_pdf(
        font_config=FontConfiguration()
    )
