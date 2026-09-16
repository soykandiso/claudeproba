"""Municipal "Јавни повици" listings: one fetcher, one config block per municipality (P1 s19).

docs/sources.md §1 and §5: once one municipality works, others should be
configuration, not code. A municipality whose site lists calls as boxes -- a title
linking straight to the call document, a deadline, links to attachments -- is added
by an entry in config/sources.yaml with `access_method: pdf_index` and an `options`
block (validated by `ListingOptions` below). This module registers one fetcher per
such entry, under that entry's slug. A site shaped differently needs its own module.

Built against Град Скопје (skopje.gov.mk, observed 16.09.2026):

- The listing is a year-long archive, not the open calls: 38 entries, deadlines
  from 31.10.2025 to 30.11.2026, no pagination. A call is in scope while its
  "Отворен до" date is today or later in Skopje; one whose date passed drops out of
  scope and is closed like any unlisted call.
- The title links the call document itself (a scanned PDF, OCR'd by the pipeline:
  decisions.md D9), so that document's URL is also the public URL.
- Procurement tenders sit in the same list ("Јавен повик за набавка…", with RAR or
  ZIP dossiers). Titles matching `exclude_titles` are not fetched. Everything else
  that is not funding (taxi licences, board nominations, urban furniture locations)
  goes to extraction, where the model can say "not a funding call" and a reviewer
  sees it: a keyword list is for the unmistakable only.
- Attachments whose label matches `document_labels` ("Критериуми") are documents
  of the call, extracted with it; the rest (forms, the general rulebook) are listed
  for the reviewer.

An entry with no boxes at all fails the crawl: an archive of a year's calls is
never empty, so an empty page means a changed site.
"""

import datetime as dt
import re
from dataclasses import dataclass
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from selectolax.lexbor import LexborHTMLParser

from app.ingestion.fetcher import CrawlContext, Fetcher
from app.ingestion.http import Request
from app.ingestion.source_config import SourceEntry, load_sources
from app.ingestion.sources import register
from app.models.enums import AccessMethod

KIND = "municipal_listing"
_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_SPACE = re.compile(r"\s+")


class ListingOptions(BaseModel):
    """The `options` block of a municipal entry in config/sources.yaml."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=f"^{KIND}$")
    listing_url: str = Field(pattern=r"^https?://")
    item: str  # CSS selector for one call's box
    title: str  # within an item: the link to the call document
    deadline: str  # within an item: the element whose text holds dd.mm.yyyy
    attachments: str  # within an item: links to further files
    document_labels: list[str] = []  # attachment labels that are part of the call text
    exclude_titles: list[str] = []  # case-insensitive substrings: never a funding call
    timezone: str = "Europe/Skopje"


@dataclass(frozen=True)
class Item:
    title: str
    url: str
    deadline: dt.date | None
    attachments: list[tuple[str, str]]  # (label, url)

    def open_on(self, day: dt.date) -> bool:
        return self.deadline is None or self.deadline >= day


def _text(node) -> str:
    return _SPACE.sub(" ", node.text(deep=True, separator="")).strip()


def _date(text: str) -> dt.date | None:
    match = _DATE.search(text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    return dt.date(year, month, day)


def parse_listing(html: str, options: ListingOptions, base_url: str) -> list[Item]:
    tree = LexborHTMLParser(html)
    items = []
    for box in tree.css(options.item):
        link = box.css_first(options.title)
        if link is None or not link.attributes.get("href"):
            raise ValueError(f"a listing item has no title link ({options.title!r})")
        deadline_node = box.css_first(options.deadline)
        items.append(
            Item(
                title=_text(link),
                url=urljoin(base_url, link.attributes["href"]),
                deadline=_date(_text(deadline_node)) if deadline_node is not None else None,
                attachments=[
                    (_text(a), urljoin(base_url, a.attributes["href"]))
                    for a in box.css(options.attachments)
                    if a.attributes.get("href")
                ],
            )
        )
    if not items:
        raise ValueError(f"listing {options.listing_url} has no items ({options.item!r})")
    return items


def excluded(item: Item, options: ListingOptions) -> bool:
    title = item.title.casefold()
    return any(word.casefold() in title for word in options.exclude_titles)


def is_document(label: str, options: ListingOptions) -> bool:
    return any(word.casefold() in label.casefold() for word in options.document_labels)


class MunicipalFetcher(Fetcher):
    options: ListingOptions
    listing_is_complete = True  # the whole archive on one page; scope is by deadline

    def __init__(self, today=None):
        tz = ZoneInfo(self.options.timezone)
        self.today = today or (lambda: dt.datetime.now(tz).date())

    def crawl(self, ctx: CrawlContext) -> None:
        options = self.options
        listing = ctx.fetch(Request(options.listing_url))
        today = self.today()
        html = listing.response.content.decode("utf-8", errors="replace")
        for item in parse_listing(html, options, listing.response.final_url):
            if not item.open_on(today) or excluded(item, options):
                continue
            documents = [ctx.fetch(Request(item.url))]
            listed = []
            for label, url in item.attachments:
                if is_document(label, options):
                    documents.append(ctx.fetch(Request(url)))
                listed.append(f"{label}: {url}")
            ctx.found_call(
                item.url,
                documents,
                listing={
                    "title": item.title,
                    "open_until": item.deadline.strftime("%d.%m.%Y") if item.deadline else "",
                    "attachments": "\n".join(listed),
                },
            )


def is_municipal(entry: SourceEntry) -> bool:
    return entry.access_method == AccessMethod.PDF_INDEX and entry.options.get("kind") == KIND


def fetcher_for(entry: SourceEntry) -> type[MunicipalFetcher]:
    """A fetcher class for one configured municipality. Invalid options raise here."""
    options = ListingOptions.model_validate(entry.options)
    name = "".join(part.title() for part in entry.slug.split("-")) + "Fetcher"
    return type(name, (MunicipalFetcher,), {"slug": entry.slug, "options": options})


for _entry in load_sources():
    if is_municipal(_entry):
        register(fetcher_for(_entry))
