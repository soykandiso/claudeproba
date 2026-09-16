"""Агенција за вработување (av.gov.mk): calls to employers under active employment measures.

The public listing (oglasi-za-aktivni-merki.nspx) is empty without JavaScript; it
fills itself from two ASP.NET JSON endpoints, which this fetcher calls directly
(docs/sources.md §1, §6.3). robots.txt allows /services/.

1. GetActiveEmploymentMeasures returns every announcement since 2016 in one
   response, each with an `ActiveMeasureIsArchived` flag.
2. For each announcement that is not archived and has a text for legal entities
   (`PbBusinessDescriptionMKD`), GetActiveEmploymentMeasureDescriptionForBusinessMk
   returns the call text as HTML, wrapped in {"d": "..."}.

Announcements only for individuals (self-employment for unemployed persons, for
example) are not fetched: the product matches companies. The listing is the
whole archive, so a call no longer listed as active can be closed.

There is no per-call public page; a person reads the text in a dialog on the
listing page, so that page is the URL shown next to citations.
"""

import json

from app.ingestion.fetcher import CrawlContext, Fetcher
from app.ingestion.http import Request
from app.ingestion.normalise import NormaliseError
from app.ingestion.sources import register

SERVICE = "https://av.gov.mk/services/ServiceJobAnnouncements.asmx"
LISTING_URL = f"{SERVICE}/GetActiveEmploymentMeasures"
DETAIL_URL = f"{SERVICE}/GetActiveEmploymentMeasureDescriptionForBusinessMk"
PUBLIC_URL = "https://av.gov.mk/oglasi-za-aktivni-merki.nspx"

_JSON = {"Content-Type": "application/json; charset=utf-8"}


def detail_request(announcement_id: int) -> Request:
    # Compact, key-ordered JSON: the body is part of the snapshot's identity
    # (Request.identity), so it must be byte-identical on every run.
    body = json.dumps({"detailId": announcement_id}, separators=(",", ":")).encode()
    return Request(DETAIL_URL, method="POST", body=body, headers=_JSON)


def open_business_announcements(listing: bytes) -> list[dict]:
    try:
        items = json.loads(listing)["d"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"AV listing is not the expected JSON: {exc}") from exc
    if not isinstance(items, list):
        raise ValueError("AV listing 'd' is not a list")
    if not items:
        # The endpoint returns the whole archive; empty means broken, not quiet.
        raise ValueError("AV listing returned no announcements at all")
    return [
        item
        for item in items
        if item.get("ActiveMeasureIsArchived") is False
        and item.get("PbBusinessDescriptionMKD") == 1
    ]


@register
class AvFetcher(Fetcher):
    slug = "av"
    listing_is_complete = True

    def unwrap(self, content: bytes, content_type: str | None) -> tuple[bytes, str | None]:
        try:
            markup = json.loads(content)["d"]
        except (ValueError, KeyError, TypeError) as exc:
            raise NormaliseError(f"AV description is not the expected JSON: {exc}") from exc
        if not isinstance(markup, str) or not markup.strip():
            raise NormaliseError("AV description is empty")
        return markup.encode("utf-8"), "text/html; charset=utf-8"

    def crawl(self, ctx: CrawlContext) -> None:
        listing = ctx.fetch(Request(LISTING_URL, method="POST", body=b"{}", headers=_JSON))
        for item in open_business_announcements(listing.response.content):
            detail = ctx.fetch(detail_request(int(item["AnnouncementId"])))
            ctx.found_call(
                PUBLIC_URL,
                [detail],
                listing={
                    "announcement_id": str(item["AnnouncementId"]),
                    "description": str(item.get("AnnouncementDescription") or ""),
                    "purpose": str(item.get("AnnouncementPurpose") or ""),
                    "listed_from": str(item.get("AnnouncementDateFromDateFormat") or ""),
                    "listed_to": str(item.get("AnnouncementDateToDateFormat") or ""),
                },
            )
