"""Министерство за економија и труд (economy.gov.mk): open public calls (roadmap P1 s18).

Server-rendered HTML (docs/sources.md §1, §6.2). robots.txt disallows only /login,
on both hosts.

1. "Јавни огласи" lists only open calls, one row each: title linking to the call
   page, the advertising institution, and a deadline in dd/mm/yyyy. Closed calls
   move to a separate "Завршени јавни огласи" listing, and news lives elsewhere
   entirely, so nothing on this listing is news. A row is a link to a page under
   /javni-objavi/javni-oglasi/; the menu's links point elsewhere.
2. A call page repeats title, institution and deadline, and links the documents on
   portal.mdt.gov.mk: "Јавен повик" (the call text, PDF or DOCX), then forms
   ("Барање", "Образец …", sometimes "Упатство").

**The document is the call text only.** Forms are templates for the applicant,
not conditions, and several are legacy .doc, which the normaliser refuses; making
them documents would send every call to review as unreadable. Their links go
into the listing for the reviewer. A call page with no "Јавен повик" link is
extracted from the page itself and says so in the listing.

**Most call texts are PDFs with no text layer** (§6.2): the pipeline OCRs them
(decisions.md D9), and every OCR citation is reviewed.

**An empty listing is normal here.** On 16.09.2026 it read "Во моментот нема
активни јавни огласи". That message with no rows is an empty source; no rows and
no message is a changed page, and fails the crawl.

The site is Livewire: every response carries a fresh CSRF token and component
snapshots with random ids and checksums. `significant` removes them, or every
page would look changed on every run.

Paging: 25 rows a page. The ministry has published 3 to 8 calls a year, so a full
page has never been seen; if one appears the crawl fails loudly rather than
quietly closing calls on page two.
"""

import datetime as dt
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from app.ingestion.fetcher import CrawlContext, Fetcher
from app.ingestion.http import Request
from app.ingestion.sources import register

LISTING_URL = "https://www.economy.gov.mk/mk-MK/javni-objavi/javni-oglasi"
CALL_PATH = "/mk-MK/javni-objavi/javni-oglasi/"
PAGE_SIZE = 25
EMPTY_MESSAGE = "нема активни јавни огласи"

_DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Row:
    title: str
    url: str
    institution: str
    deadline: str  # dd.mm.yyyy, or "" when the row shows none


@dataclass(frozen=True)
class CallPage:
    title: str
    institution: str
    deadline: str  # dd.mm.yyyy
    call_text_url: str | None
    attachments: list[tuple[str, str]]  # (label, url), in page order, call text included


def _text(node) -> str:
    # Inline spans join with nothing added: the site splits "2026" as "202<span>6</span>"
    # (the same trap as AV, docs/sources.md §6.3).
    return _SPACE.sub(" ", node.text(deep=True, separator="")).strip()


def _date(text: str) -> str:
    match = _DATE.search(text)
    if not match:
        return ""
    day, month, year = match.groups()
    dt.date(int(year), int(month), int(day))  # refuses 31/02/2026 rather than showing it
    return f"{day}.{month}.{year}"


def listing_rows(html: str, base_url: str = LISTING_URL) -> list[Row]:
    tree = LexborHTMLParser(html)
    rows: dict[str, Row] = {}
    for link in tree.css("a[href]"):
        url = urljoin(base_url, link.attributes.get("href") or "")
        path = urlsplit(url).path
        if not path.startswith(CALL_PATH) or path.rstrip("/") == CALL_PATH.rstrip("/"):
            continue
        # The row is the nearest ancestor that also holds the deadline cell.
        row = link.parent
        while row is not None and not _DATE.search(row.text() or ""):
            row = row.parent
        cells = [_text(cell) for cell in row.iter()] if row is not None else []
        institution = next((c for c in cells if c and c != _text(link) and not _DATE.search(c)), "")
        rows.setdefault(
            url,
            Row(_text(link), url, institution, _date(row.text() if row is not None else "")),
        )
    if not rows and EMPTY_MESSAGE not in (tree.body.text() if tree.body else ""):
        raise ValueError("Economy listing has no calls and no 'no active calls' message")
    if len(rows) >= PAGE_SIZE:
        raise ValueError(f"Economy listing shows {len(rows)} calls: a second page is not read")
    return list(rows.values())


def call_page(html: str, base_url: str) -> CallPage:
    tree = LexborHTMLParser(html)
    headings = [_text(h) for h in tree.css("h1") if _text(h)]
    if not headings:
        raise ValueError(f"Economy call page has no title: {base_url}")
    body = _text(tree.body) if tree.body else ""
    institution = ""
    match = re.search(r"Институција која огласува:\s*(.+?)\s*Рок на пријавување:", body)
    if match:
        institution = match.group(1)
    deadline_match = re.search(r"Рок на пријавување:\s*(\d{2}/\d{2}/\d{4})", body)
    attachments = []
    for link in tree.css("a[href]"):
        url = urljoin(base_url, link.attributes.get("href") or "")
        if "/post-body-files/" not in urlsplit(url).path:
            continue
        label = _text(link).removesuffix(">>>").strip()
        attachments.append((label, url))
    call_text = next(
        (url for label, url in attachments if label.casefold().startswith("јавен повик")), None
    )
    return CallPage(
        title=headings[-1],
        institution=institution,
        deadline=_date(deadline_match.group(1)) if deadline_match else "",
        call_text_url=call_text,
        attachments=attachments,
    )


_LIVEWIRE_STATE = re.compile(
    rb'(<meta name="csrf-token" content=")[^"]*(")'
    rb'|(data-csrf=")[^"]*(")'
    rb'|(wire:snapshot=")[^"]*(")'
    rb'|(wire:id=")[^"]*(")'
)


def without_livewire_state(content: bytes) -> bytes:
    """Livewire pages regenerate these on every request (observed 16.09.2026)."""
    return _LIVEWIRE_STATE.sub(lambda m: b"".join(g for g in m.groups() if g is not None), content)


@register
class EconomyFetcher(Fetcher):
    slug = "economy"
    listing_is_complete = True  # one page, open calls only; paging fails the crawl

    def significant(self, content: bytes) -> bytes:
        return without_livewire_state(content)

    def crawl(self, ctx: CrawlContext) -> None:
        listing = ctx.fetch(Request(LISTING_URL))
        for row in listing_rows(_decode(listing.response.content), listing.response.final_url):
            page_fetch = ctx.fetch(Request(row.url))
            page = call_page(_decode(page_fetch.response.content), page_fetch.response.final_url)
            if page.call_text_url:
                document = ctx.fetch(Request(page.call_text_url))
                note = ""
            else:
                document = page_fetch
                note = "no 'Јавен повик' attachment: the call page itself was extracted"
            ctx.found_call(
                row.url,
                [document],
                listing={
                    "title": row.title,
                    "institution": page.institution or row.institution,
                    "listed_deadline": row.deadline,
                    "page_deadline": page.deadline,
                    "attachments": "\n".join(f"{label}: {url}" for label, url in page.attachments),
                    "note": note,
                },
            )


def _decode(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")
