"""The only way ingestion talks to the outside world (CLAUDE.md: crawl honestly).

- A real User-Agent with a contact URL, on every request including robots.txt.
- robots.txt is fetched once per host per client and obeyed. A missing file (4xx)
  allows everything; an unreachable one (5xx, timeout) disallows everything,
  following RFC 9309 -- when in doubt, do not crawl.
- One request at a time, and at least `min_interval_s` between two requests to
  the same host (5 s for the default 0.2 requests per second).

A disallowed or failed fetch raises. Nothing here retries: a source that fails
tonight is recorded as failing and tried again tomorrow, which is what the
staleness alarm is for.
"""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from app.ingestion.robots import Robots

MAX_BYTES = 50 * 1024 * 1024  # the largest IPARD call package seen was 5 MB
ROBOTS_AGENT = "grantbot"


class FetchError(RuntimeError):
    pass


class RobotsDisallowed(FetchError):
    pass


@dataclass(frozen=True)
class Request:
    url: str
    method: str = "GET"
    body: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def identity(self) -> str:
        """What a snapshot is 'of'. A GET is its URL; a POST is its URL plus body.

        AV serves every call from one endpoint and tells them apart by the POST
        body, so the URL alone cannot identify a document. The body goes in the
        fragment, which servers never see, so the identity cannot be mistaken
        for a fetchable address.
        """
        if self.method == "GET":
            return self.url
        body = self.body or b""
        try:
            shown = body.decode("utf-8") if len(body) <= 200 else None
        except UnicodeDecodeError:
            shown = None
        shown = shown if shown is not None else "sha256=" + hashlib.sha256(body).hexdigest()
        return f"{self.url}#{self.method} {shown}"


@dataclass(frozen=True)
class Response:
    request: Request
    status: int
    content: bytes
    content_type: str | None
    final_url: str


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        *,
        min_interval_s: float = 5.0,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.user_agent = user_agent
        self._min_interval = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, Robots] = {}
        self._http = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_s,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fetch(self, request: Request) -> Response:
        if not self._robots_for(request.url).can_fetch(ROBOTS_AGENT, request.url):
            raise RobotsDisallowed(f"robots.txt disallows {request.url}")

        response = self._send(request)
        if not 200 <= response.status < 300:
            raise FetchError(f"{request.method} {request.url} returned HTTP {response.status}")
        return response

    # -- internals -----------------------------------------------------------------------

    def _robots_for(self, url: str) -> Robots:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            try:
                robots = self._send(Request(f"{origin}/robots.txt"))
            except (httpx.HTTPError, FetchError):
                parsed = Robots(disallow_all=True)
            else:
                if robots.status >= 500:
                    parsed = Robots(disallow_all=True)
                elif robots.status >= 400:
                    parsed = Robots(allow_all=True)
                else:
                    parsed = Robots.parse(robots.content.decode("utf-8-sig", errors="replace"))
            self._robots[origin] = parsed
        return self._robots[origin]

    def _send(self, request: Request) -> Response:
        host = urlsplit(request.url).netloc
        if host in self._last_request:
            wait = self._last_request[host] + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        try:
            with self._http.stream(
                request.method, request.url, content=request.body, headers=request.headers
            ) as raw:
                chunks, size = [], 0
                for chunk in raw.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FetchError(f"{request.url} is larger than {MAX_BYTES} bytes")
                    chunks.append(chunk)
                return Response(
                    request=request,
                    status=raw.status_code,
                    content=b"".join(chunks),
                    content_type=raw.headers.get("content-type"),
                    final_url=str(raw.url),
                )
        finally:
            # Counted from the end of the request, so a slow download does not
            # shorten the pause before the next one.
            self._last_request[host] = self._clock()
