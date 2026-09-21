"""АФПЗРР / IPARD (ipardpa.gov.mk): calls under the IPARD 2021-2027 programme (P1 s20).

Server-rendered ASP.NET, no robots.txt (404: everything allowed). docs/sources.md
§1, §6.2, §6.3, §6.9.

1. The programme page lists every call of the programme, newest first, as links to
   /mk/Home/IpardPovici/<id>: an archive with no dates.
2. A call page lists the call's files. They arrive in stages on the same page: an
   advance notice ("ПРЕТХОДНА НАЈАВА"), then the call in a short and a long version
   ("Кратка верзија", "Долга верзија") with forms and guides, and finally a ranking
   of applications ("РАНГ ЛИСТА").

**The call page is the primary document.** Its URL stays the same through all
stages, so an announced call and the published call are one call: when files are
added the page changes, and the pipeline updates the call instead of creating a
second one (pipeline._call_for matches on the primary document's URL). Its text,
taken from the content section only (`html_root`), is the call's title and the
list of its files.

**Extracted with it:** the short and long versions once published, otherwise the
advance notice. An advance notice alone is extracted as `advance_notice`, which the
pipeline stores as ANNOUNCED. Forms and guides are listed for the reviewer.

**Scope:** a call whose page lists a ranking has been decided; it is not fetched,
and a call ingested earlier is closed when its ranking appears. Calls that only
ever had a notice (02/2025 and 03/2025 on 16.09.2026) stay announced until a
reviewer rejects them: the site gives no date to judge them by.

**Tables.** The long version sets out eligibility, eligible costs and scoring in
tables, in PDFs with no text layer. OCR reads a table row by row, so a criterion
can be quoted correctly and still be read wrongly across columns. Every IPARD call
therefore reaches the reviewer with a note to check each criterion against the
tables in the PDF: tabular eligibility is routed to a human explicitly, as the
roadmap requires, rather than trusted. The same note warns that OCR turns every "%"
into digits (docs/sources.md §6.9): co-financing rates are exactly where that bites.

ASP.NET adds a fresh __RequestVerificationToken to every page; `significant`
ignores it (snapshots.without_aspnet_state).
"""

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from app.ingestion.fetcher import CrawlContext, Fetcher
from app.ingestion.http import Request
from app.ingestion.snapshots import without_aspnet_state
from app.ingestion.sources import register

PROGRAMME_URL = "https://www.ipardpa.gov.mk/mk/Home/Ipard/5"  # IPARD 2021-2027
CALL_PATH = re.compile(r"^/mk/Home/IpardPovici/\d+$")
CONTENT = "section.section.mb-3"

RANKING = "ранг листа"
NOTICE = "претходна најава"
CALL_TEXTS = ("кратка верзија", "долга верзија")

TABLES_NOTE = (
    "IPARD eligibility, eligible costs and scoring are set out in tables in the long "
    "version. OCR reads a table row by row: check every criterion against the table in "
    "the PDF before approving."
)

_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class CallFiles:
    title: str
    files: list[tuple[str, str]]  # (label, url) in page order

    def labelled(self, *words: str) -> list[tuple[str, str]]:
        return [
            (label, url) for label, url in self.files if any(w in label.casefold() for w in words)
        ]

    @property
    def decided(self) -> bool:
        return bool(self.labelled(RANKING))

    def documents(self) -> list[tuple[str, str]]:
        """The files extracted with the page: the call versions, else the notice."""
        return self.labelled(*CALL_TEXTS) or self.labelled(NOTICE)


def _text(node) -> str:
    return _SPACE.sub(" ", node.text(deep=True, separator="")).strip()


def programme_calls(html: str, base_url: str = PROGRAMME_URL) -> list[str]:
    tree = LexborHTMLParser(html)
    urls = []
    for link in tree.css("a[href]"):
        url = urljoin(base_url, link.attributes["href"])
        if CALL_PATH.match(urlsplit(url).path) and url not in urls:
            urls.append(url)
    if not urls:
        raise ValueError("IPARD programme page lists no calls: the page has changed")
    return urls


def call_files(html: str, base_url: str) -> CallFiles:
    content = LexborHTMLParser(html).css_first(CONTENT)
    if content is None:
        raise ValueError(f"IPARD call page has no content section ({CONTENT}): {base_url}")
    heading = next((_text(h) for h in content.css("h1, h2, h3, h4") if _text(h)), "")
    files = []
    for link in content.css("a[href]"):
        url = urljoin(base_url, link.attributes["href"])
        if "/Upload/" in urlsplit(url).path and (label := _text(link)):
            files.append((label, url))
    return CallFiles(heading, files)


@register
class IpardFetcher(Fetcher):
    slug = "ipard"
    listing_is_complete = True  # the whole programme on one page; decided calls are out of scope

    def significant(self, content: bytes) -> bytes:
        return without_aspnet_state(content)

    def html_root(self, url: str) -> str | None:
        return CONTENT if CALL_PATH.match(urlsplit(url).path) else None

    def crawl(self, ctx: CrawlContext) -> None:
        programme = ctx.fetch(Request(PROGRAMME_URL))
        html = programme.response.content.decode("utf-8", errors="replace")
        for url in programme_calls(html, programme.response.final_url):
            page = ctx.fetch(Request(url))
            call = call_files(page.response.content.decode("utf-8", errors="replace"), url)
            if call.decided:
                continue
            documents = [ctx.fetch(Request(file_url)) for _, file_url in call.documents()]
            extracted = {file_url for _, file_url in call.documents()}
            ctx.found_call(
                url,
                [page, *documents],
                listing={
                    "title": call.title,
                    "stage": "call published"
                    if call.labelled(*CALL_TEXTS)
                    else "advance notice only",
                    "other_files": "\n".join(
                        f"{label}: {file_url}"
                        for label, file_url in call.files
                        if file_url not in extracted
                    ),
                    "note": TABLES_NOTE,
                },
            )
