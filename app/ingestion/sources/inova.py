"""ИНОВА (inova.gov.mk): the Agency for Innovation, Scientific-Technological Development and
Entrepreneurship, which took over from ФИТР and the entrepreneurship agency (АППРМ) in 2026.

fitr.mk lapsed in 2026 (docs/sources.md §6.1, §6.12). The new site is WordPress, and its
public REST API (`/wp-json/wp/v2/`) gives posts and pages as JSON; robots.txt disallows only
/wp-admin/. Reading the API instead of the themed HTML means a redesign of the site cannot
break the fetcher, only a change to WordPress itself could.

Two places can hold a call:

1. **Posts** whose title says «повик». The listing is the latest 100 posts, title only;
   each candidate is then fetched in full, with the documents it links from
   /wp-content/uploads/ (the call's PDF and forms, up to `MAX_ATTACHMENTS`).
2. **The «Јавни повици» page** (page 4005), each document it links being one call.

Everything else on the site (news, job advertisements, the Greening Business Facility's
description until its calls open) is not fetched. A post or document the model reads as not
a funding call goes to the review queue once, then costs nothing while it is unchanged.

The post listing is not the whole archive, so a call no longer listed is not closed by this
fetcher (`listing_is_complete` is False); its deadline closes it.
"""

import html
import json
import re

from app.ingestion.fetcher import CrawlContext, Fetcher
from app.ingestion.http import Request
from app.ingestion.normalise import NormaliseError
from app.ingestion.sources import register

API = "https://inova.gov.mk/wp-json/wp/v2"
POSTS_URL = f"{API}/posts?per_page=100&_fields=id,date,modified,link,title"
CALLS_PAGE_ID = 4005  # «Јавни повици», https://inova.gov.mk/јавни-повици/
CALLS_PAGE_URL = f"{API}/pages/{CALLS_PAGE_ID}?_fields=id,date,modified,link,title,content"
MAX_ATTACHMENTS = 4

_CALL = re.compile(r"повик", re.IGNORECASE)
_LINK = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_DOCUMENT = re.compile(
    r"^https://inova\.gov\.mk/wp-content/uploads/.+\.(pdf|docx?)$", re.IGNORECASE
)


def post_url(post_id: int) -> str:
    return f"{API}/posts/{post_id}?_fields=id,date,modified,link,title,content"


def _json(content: bytes, what: str):
    try:
        return json.loads(content)
    except ValueError as exc:
        raise ValueError(f"ИНОВА {what} is not JSON: {exc}") from exc


def _text(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", markup or "")).strip()


def call_posts(listing: bytes) -> list[dict]:
    """The posts whose title says «повик», newest first."""
    posts = _json(listing, "post listing")
    if not isinstance(posts, list) or not posts:
        # The site has posted since it opened; an empty list means broken, not quiet.
        raise ValueError("ИНОВА post listing is empty or not a list")
    found = []
    for post in posts:
        title = _text((post.get("title") or {}).get("rendered", ""))
        if _CALL.search(title):
            found.append({**post, "title_text": title})
    return found


def documents_in(markup: str) -> list[tuple[str, str]]:
    """The documents a post or page links from its own uploads, as (label, url), once each."""
    seen, found = set(), []
    for href, label in _LINK.findall(markup or ""):
        url = html.unescape(href)
        if _DOCUMENT.match(url) and url not in seen:
            seen.add(url)
            found.append((_text(label) or url.rsplit("/", 1)[-1], url))
    return found


@register
class InovaFetcher(Fetcher):
    slug = "inova"
    listing_is_complete = False

    def unwrap(self, content: bytes, content_type: str | None) -> tuple[bytes, str | None]:
        if not (content_type or "").startswith("application/json"):
            return content, content_type  # a PDF or a Word file, as served
        try:
            item = json.loads(content)
            title = item["title"]["rendered"]
            body = item["content"]["rendered"]
        except (ValueError, KeyError, TypeError) as exc:
            raise NormaliseError(f"ИНОВА item is not the expected JSON: {exc}") from exc
        if not _text(body):
            raise NormaliseError("ИНОВА item has no text")
        return f"<h1>{title}</h1>\n{body}".encode(), "text/html; charset=utf-8"

    def crawl(self, ctx: CrawlContext) -> None:
        listing = ctx.fetch(Request(POSTS_URL))
        for post in call_posts(listing.response.content):
            detail = ctx.fetch(Request(post_url(int(post["id"]))))
            content = (_json(detail.response.content, "post").get("content") or {}).get(
                "rendered", ""
            )
            attached = documents_in(content)[:MAX_ATTACHMENTS]
            ctx.found_call(
                post["link"],
                [detail] + [ctx.fetch(Request(url)) for _, url in attached],
                listing={
                    "title": post["title_text"],
                    "published": str(post.get("date") or ""),
                    "modified": str(post.get("modified") or ""),
                    "attachments": "\n".join(f"{label}: {url}" for label, url in attached),
                },
            )

        page = ctx.fetch(Request(CALLS_PAGE_URL))
        item = _json(page.response.content, "calls page")
        for label, url in documents_in((item.get("content") or {}).get("rendered", "")):
            ctx.found_call(
                item.get("link") or url,
                [ctx.fetch(Request(url))],
                listing={"title": label, "note": "listed on ИНОВА's «Јавни повици» page"},
            )
