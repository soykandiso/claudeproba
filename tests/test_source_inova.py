"""The ИНОВА fetcher's parsing, against the API responses captured on 15.10.2026.

Captured with the crawler's own client (`PoliteClient`, our User-Agent, robots.txt read):
the post listing, post 2924 («Самовработување со грант 2026») and page 4005 («Јавни повици»).
"""

import json
from pathlib import Path

import pytest

from app.ingestion.normalise import NormaliseError, normalise
from app.ingestion.sources import fetchers
from app.ingestion.sources.inova import (
    CALLS_PAGE_URL,
    POSTS_URL,
    InovaFetcher,
    call_posts,
    documents_in,
    post_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "inova"


def listing(extra_titles=()) -> bytes:
    posts = json.loads((FIXTURES / "posts.json").read_bytes())
    for n, title in enumerate(extra_titles):
        posts.insert(
            n,
            {
                "id": 90000 + n,
                "date": "2026-10-20T09:00:00",
                "modified": "2026-10-20T09:00:00",
                "link": f"https://inova.gov.mk/p{n}/",
                "title": {"rendered": title},
            },
        )
    return json.dumps(posts).encode()


def test_the_fetcher_is_registered_and_reads_the_api():
    assert fetchers()["inova"] is InovaFetcher and not InovaFetcher.listing_is_complete
    assert POSTS_URL.startswith("https://inova.gov.mk/wp-json/wp/v2/posts?")
    assert "/pages/4005?" in CALLS_PAGE_URL and post_url(7).endswith(
        "/posts/7?_fields=id,date,modified,link,title,content"
    )


def test_news_and_job_advertisements_are_not_calls():
    # 15.10.2026: thirteen posts, none of them a call to apply for money.
    assert call_posts(listing()) == []


def test_a_post_that_says_povik_is_a_call_candidate_whatever_its_case_and_entities():
    titles = [
        "ЈАВЕН ПОВИК за мали ко-грантови &#8211; Greening Business Facility",
        "Повик за советодавна поддршка",
    ]
    found = call_posts(listing(titles))
    assert [p["title_text"] for p in found] == [
        "ЈАВЕН ПОВИК за мали ко-грантови – Greening Business Facility",
        "Повик за советодавна поддршка",
    ]


@pytest.mark.parametrize("body", [b"[]", b"<html>maintenance</html>", b'{"code": "rest_disabled"}'])
def test_a_broken_listing_fails_the_crawl_instead_of_looking_quiet(body):
    with pytest.raises(ValueError):
        call_posts(body)


def test_documents_are_the_sites_own_uploads_once_each():
    post = json.loads((FIXTURES / "post-2924.json").read_bytes())["content"]["rendered"]
    urls = [url for _, url in documents_in(post)]
    assert urls and all(u.startswith("https://inova.gov.mk/wp-content/uploads/") for u in urls)
    assert not any(
        "av.gov.mk" in u for u in urls
    )  # a link to another site is not a document of this call
    assert len(urls) == len(set(urls))


def test_the_calls_page_lists_its_two_calls():
    page = json.loads((FIXTURES / "page-4005.json").read_bytes())["content"]["rendered"]
    assert [url.rsplit("/", 1)[-1] for _, url in documents_in(page)] == [
        "Javen-Povik-br.-4_2025.pdf",
        "Javen-Povik-4_2025-organizacii-za-delovna-poddrshka.pdf",
    ]


def test_unwrap_gives_the_normaliser_the_post_as_html():
    content, content_type = InovaFetcher().unwrap(
        (FIXTURES / "post-2924.json").read_bytes(), "application/json; charset=UTF-8"
    )
    assert content_type == "text/html; charset=utf-8"
    text = normalise(content, content_type).text
    assert "Самовработување со грант 2026" in text and "Оперативен план" in text


def test_a_document_passes_through_unwrap_as_served():
    assert InovaFetcher().unwrap(b"%PDF-1.7 ...", "application/pdf") == (
        b"%PDF-1.7 ...",
        "application/pdf",
    )


@pytest.mark.parametrize(
    "body", [b"{}", b'{"title": {"rendered": "x"}, "content": {"rendered": "  "}}', b"not json"]
)
def test_an_unexpected_item_is_a_normalise_error(body):
    with pytest.raises(NormaliseError):
        InovaFetcher().unwrap(body, "application/json")
