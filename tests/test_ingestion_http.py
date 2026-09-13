"""Crawl honestly: User-Agent, robots.txt and rate limit, checked without a network."""

import httpx
import pytest

from app.ingestion.http import FetchError, PoliteClient, Request, RobotsDisallowed
from app.ingestion.robots import Robots

UA = "grantbot/0.1 (+https://example.invalid/crawler)"


class Site:
    """A fake web server that records what it was asked."""

    def __init__(self, robots: tuple[int, str] = (200, "User-agent: *\nDisallow: /private/\n")):
        self.robots = robots
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/robots.txt":
            status, body = self.robots
            return httpx.Response(status, text=body)
        if request.url.path == "/missing":
            return httpx.Response(404, text="not here")
        return httpx.Response(
            200, content=b"page:" + request.url.path.encode(), headers={"content-type": "text/html"}
        )


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def client_for(site: Site, clock: FakeClock | None = None) -> PoliteClient:
    clock = clock or FakeClock()
    return PoliteClient(
        UA,
        min_interval_s=5.0,
        transport=httpx.MockTransport(site.handler),
        clock=clock,
        sleep=clock.sleep,
    )


def test_every_request_identifies_itself_including_robots():
    site = Site()
    client_for(site).fetch(Request("https://gov.example/calls"))

    assert [r.url.path for r in site.requests] == ["/robots.txt", "/calls"]
    assert all(r.headers["user-agent"] == UA for r in site.requests)


def test_robots_disallow_is_obeyed_before_any_request_to_the_page():
    site = Site()

    with pytest.raises(RobotsDisallowed):
        client_for(site).fetch(Request("https://gov.example/private/call.pdf"))

    assert [r.url.path for r in site.requests] == ["/robots.txt"]


def test_missing_robots_allows():
    site = Site(robots=(404, "Not Found"))

    assert client_for(site).fetch(Request("https://gov.example/private/x")).status == 200


def test_unreachable_robots_disallows():
    site = Site(robots=(503, "down"))

    with pytest.raises(RobotsDisallowed):
        client_for(site).fetch(Request("https://gov.example/calls"))


def test_av_style_pdf_ban_is_respected():
    """av.gov.mk's real rule (docs/sources.md §6)."""
    site = Site(robots=(200, "User-agent: *\nDisallow: *.pdf\n"))
    client = client_for(site)

    client.fetch(Request("https://av.gov.mk/services/Service.asmx/List", method="POST", body=b"{}"))
    with pytest.raises(RobotsDisallowed):
        client.fetch(Request("https://av.gov.mk/content/plan.pdf"))


def test_requests_to_one_host_are_spaced_by_the_minimum_interval():
    site, clock = Site(), FakeClock()
    client = client_for(site, clock)

    client.fetch(Request("https://gov.example/a"))  # robots, then /a: one wait between them
    client.fetch(Request("https://gov.example/b"))

    assert clock.slept == [5.0, 5.0]


def test_different_hosts_do_not_wait_for_each_other():
    site, clock = Site(), FakeClock()
    client = client_for(site, clock)

    client.fetch(Request("https://one.example/a"))
    clock.slept.clear()
    client.fetch(Request("https://two.example/a"))  # robots on a new host: no wait

    assert clock.slept == [5.0]  # only between two.example's robots.txt and its page


def test_an_http_error_raises_rather_than_returning_an_error_page():
    with pytest.raises(FetchError, match="404"):
        client_for(Site()).fetch(Request("https://gov.example/missing"))


def test_post_identity_includes_the_body():
    one = Request("https://av.gov.mk/x.asmx/Detail", method="POST", body=b"{detailId:820}")
    two = Request("https://av.gov.mk/x.asmx/Detail", method="POST", body=b"{detailId:819}")

    assert one.identity == "https://av.gov.mk/x.asmx/Detail#POST {detailId:820}"
    assert one.identity != two.identity
    assert Request("https://gov.example/a").identity == "https://gov.example/a"


# --- robots.txt matching, including the real files seen in reconnaissance ------------


def test_robots_rules_follow_rfc_9309():
    robots = Robots.parse(
        "User-agent: *\n"
        "Disallow: /private/\n"
        "Allow: /private/public-calls/\n"
        "Disallow: /*.xls$\n"
        "\n"
        "User-agent: grantbot\n"
        "Disallow: /no-bots/\n"
    )

    assert robots.can_fetch("grantbot", "https://x/private/") is True, "own group replaces *"
    assert robots.can_fetch("grantbot", "https://x/no-bots/a") is False
    assert robots.can_fetch("other", "https://x/private/a") is False
    assert robots.can_fetch("other", "https://x/private/public-calls/1") is True, "longest wins"
    assert robots.can_fetch("other", "https://x/data/report.xls") is False
    assert robots.can_fetch("other", "https://x/data/report.xlsx") is True, "$ anchors"


def test_av_gov_mk_robots_as_served_on_13_09_2026():
    robots = Robots.parse(
        "﻿User-agent: *\nDisallow: /bin/\nDisallow: /datasource/\nDisallow: /index/\n"
        "Disallow: /temp/\nDisallow: *.pdf\nSitemap: sitemap.xml\n"
    )

    assert not robots.can_fetch("grantbot", "https://av.gov.mk/content/Operativen plan 2026.pdf")
    assert not robots.can_fetch("grantbot", "https://av.gov.mk/bin/x")
    assert robots.can_fetch(
        "grantbot",
        "https://av.gov.mk/services/ServiceJobAnnouncements.asmx/GetActiveEmploymentMeasures",
    )


def test_an_empty_disallow_allows_everything():
    assert Robots.parse("User-agent: *\nDisallow:\n").can_fetch("grantbot", "https://x/anything")
