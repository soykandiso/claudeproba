"""EU Funding & Tenders Portal: grant topics from programmes North Macedonia takes part in.

No HTML is scraped. Two JSON services, both allowed by robots.txt (docs/sources.md §1):

1. The search API (api.tech.ec.europa.eu/search-api, public key SEDIA) lists
   topics. It is a POST with multipart parts `query`, `languages` and `sort`, and
   pages by `pageNumber`; every page is fetched, and a listing whose result count
   does not add up to `totalResults` fails the crawl rather than closing calls it
   simply did not see.
2. For each topic in scope, `…/data/topicDetails/<identifier>.json` holds the
   topic text as HTML fields plus structured dates.

**Scope** (SCOPE below; docs/decisions.md D10). The portal lists ~1.300 open and
forthcoming items, 966 of them Horizon Europe research topics (13.09.2026). Every
new call waits for a human approval, so ingesting all of them would bury the
review queue. The default takes grant topics (type 1) from programmes North
Macedonia is associated to and that a company or NGO can realistically lead:
Digital Europe, the Single Market Programme, Creative Europe, Erasmus+, and the
EIC part of Horizon Europe. Widening it is an edit to SCOPE.

**The portal's own status is not trusted.** On 16.09.2026 it listed EIC topics
whose last deadline was in 2023 as "Open". A topic is in scope only while one of
its deadlines is today or later (UTC), or it has none yet.

**The document.** `unwrap` renders a topic's JSON as HTML: title, identifiers,
dates, description and conditions. The source's HTML fields are used as served;
the labels and the dd.mm.yyyy dates are this module's rendering of structured
fields, deterministic from the stored bytes, so a quote from them is still found
verbatim in the snapshot's text. The deadline times in the JSON are not reliable
(00:00 UTC for most 2026 topics, 17:00 UTC for older ones), so
only the date is rendered.

**What is not extracted yet.** Most topics' conditions say "Eligible countries:
described in the call document": eligibility lives in a PDF linked from the
conditions (a call document, the EIC Work Programme, a Chips JU page), often
shared by many topics. Those links go into the listing for the reviewer;
fetching and extracting those documents is a later session (docs/sources.md §6.6).

Search pages carry `responseTime` and other per-request fields, and a topic's JSON
changes whenever its call's news (`latestInfos`) does, which is often shared by
every topic in the call. `significant` compares only what matters: the listed
identifiers, statuses and deadlines for a search page, and the rendered document
for a topic, so neither re-runs extraction.
"""

import datetime as dt
import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.ingestion.fetcher import CrawlContext, Fetcher
from app.ingestion.http import Request
from app.ingestion.normalise import NormaliseError
from app.ingestion.sources import register

SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/{}.json"
PUBLIC_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/"
    "topic-details/{}"
)

PAGE_SIZE = 100
MAX_PAGES = 20  # 2.000 results per query; far above any scope below

TYPE_GRANT_TOPIC = "1"
STATUS_FORTHCOMING, STATUS_OPEN = "31094501", "31094502"


@dataclass(frozen=True)
class Scope:
    name: str
    field: str  # a search-API metadata field
    values: tuple[str, ...]


# IDs read from the search API's facets on 16.09.2026. North Macedonia's association
# to each programme: docs/decisions.md D10.
SCOPE = (
    Scope(
        "programmes",
        "frameworkProgramme",
        (
            "43152860",  # Digital Europe Programme (DIGITAL)
            "43252476",  # Single Market Programme (SMP)
            "43251814",  # Creative Europe Programme (CREA)
            "43353764",  # Erasmus+ (ERASMUS)
        ),
    ),
    Scope("horizon-eic", "programmeDivision", ("43121666",)),  # The European Innovation Council
)

_BOUNDARY = "grantbot-eu-portal"  # fixed: the body is part of each page's snapshot identity


def search_request(scope: Scope, page: int) -> Request:
    query = {
        "bool": {
            "must": [
                {"terms": {"type": [TYPE_GRANT_TOPIC]}},
                {"terms": {"status": [STATUS_FORTHCOMING, STATUS_OPEN]}},
                {"terms": {scope.field: list(scope.values)}},
            ]
        }
    }
    parts = {
        "query": query,
        "languages": ["en"],
        # A stable order, so pages do not overlap or skip while the crawl runs.
        "sort": {"field": "identifier", "order": "ASC"},
    }
    body = (
        b"".join(
            (
                f"--{_BOUNDARY}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                "Content-Type: application/json\r\n\r\n"
                f"{json.dumps(value, separators=(',', ':'), sort_keys=True)}\r\n"
            ).encode()
            for name, value in parts.items()
        )
        + f"--{_BOUNDARY}--\r\n".encode()
    )
    url = f"{SEARCH_URL}?apiKey=SEDIA&text=***&pageSize={PAGE_SIZE}&pageNumber={page}"
    return Request(
        url,
        method="POST",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={_BOUNDARY}"},
    )


def topic_request(identifier: str) -> Request:
    return Request(TOPIC_URL.format(identifier.lower()))


@dataclass(frozen=True)
class Page:
    total: int
    results: list[dict]


def parse_search(content: bytes) -> Page:
    try:
        data = json.loads(content)
        total, results = data["totalResults"], data["results"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"EU search response is not the expected JSON: {exc}") from exc
    if not isinstance(total, int) or not isinstance(results, list):
        raise ValueError("EU search response has no result count or result list")
    return Page(total, results)


def _first(metadata: dict, key: str) -> str | None:
    values = metadata.get(key)
    if isinstance(values, list) and values:
        return str(values[0])
    return None


def in_scope(results: list[dict], today: dt.date) -> list[dict]:
    """One result per topic identifier, only grant topics with a deadline still ahead.

    The search returns the same identifier more than once (docs/sources.md §6.3).
    """
    kept: dict[str, dict] = {}
    for result in results:
        metadata = result.get("metadata") or {}
        identifier = _first(metadata, "identifier")
        if not identifier or _first(metadata, "type") != TYPE_GRANT_TOPIC:
            continue
        deadlines = [_iso_date(value) for value in metadata.get("deadlineDate") or []]
        if deadlines and max(deadlines) < today:
            continue
        kept.setdefault(identifier, result)
    return list(kept.values())


def _iso_date(value: str) -> dt.date:
    return dt.datetime.fromisoformat(value.replace("+0000", "+00:00")).astimezone(dt.UTC).date()


def _epoch_date(value) -> str:
    moment = dt.datetime.fromtimestamp(int(value) / 1000, tz=dt.UTC)
    return moment.strftime("%d.%m.%Y")


def _topic(content: bytes) -> dict:
    try:
        topic = json.loads(content)["TopicDetails"]
    except (ValueError, KeyError, TypeError) as exc:
        raise NormaliseError(f"EU topic is not the expected JSON: {exc}") from exc
    if not isinstance(topic, dict) or not topic.get("identifier") or not topic.get("title"):
        raise NormaliseError("EU topic has no identifier or title")
    return topic


def render_topic(topic: dict) -> str:
    """The topic as one HTML document. Only what a reviewer and the extractor need."""
    identifier = topic["identifier"]
    lines = [
        f"<h1>{html.escape(topic['title'])}</h1>",
        f"<p>Topic ID: {html.escape(identifier)}</p>",
    ]

    def line(label: str, value) -> None:
        if value:
            lines.append(f"<p>{label}: {html.escape(str(value))}</p>")

    programme = topic.get("frameworkProgramme") or {}
    line("Programme", programme.get("description"))
    if topic.get("callIdentifier"):
        call = topic["callIdentifier"]
        line("Call", f"{topic.get('callTitle')} ({call})" if topic.get("callTitle") else call)
    if topic.get("publicationDateLong"):
        line("Publication date", _epoch_date(topic["publicationDateLong"]))

    opening, deadlines, types = set(), set(), []
    for action in topic.get("actions") or []:
        if action.get("plannedOpeningDate"):
            opening.add(int(action["plannedOpeningDate"]))
        deadlines.update(int(value) for value in action.get("deadlineDates") or [])
        types.extend(
            t.get("typeOfAction") for t in action.get("types") or [] if t.get("typeOfAction")
        )
    line("Type of action", "; ".join(dict.fromkeys(re.sub(r"\s+", " ", t) for t in types)))
    line("Opening date", ", ".join(_epoch_date(v) for v in sorted(opening)))
    line("Deadline date", ", ".join(_epoch_date(v) for v in sorted(deadlines)))

    budget = (topic.get("budgetOverviewJSONItem") or {}).get("budgetTopicActionMap") or {}
    for entries in budget.values():
        for entry in entries or []:
            if not str(entry.get("action", "")).startswith(f"{identifier} - "):
                continue
            line("Deadline model", entry.get("deadlineModel"))
            low, high = entry.get("minContribution") or 0, entry.get("maxContribution") or 0
            if low or high:
                line("EU contribution per project, EUR", f"{low:,} to {high:,}")
            line("Indicative number of grants", entry.get("expectedGrants"))

    for heading, field in (("Topic description", "description"), ("Conditions", "conditions")):
        if topic.get(field):
            lines.append(f"<h2>{heading}</h2><div>{topic[field]}</div>")
    return "<html><body>\n" + "\n".join(lines) + "\n</body></html>\n"


_LINK = re.compile(r'<a[^>]+href="([^"]+)"', re.IGNORECASE)


ELIGIBILITY_GAP = (
    "Дел од условите на овој повик се во документот на повикот или во работната "
    "програма, кои сè уште не се прочитани."
)


def condition_links(topic: dict) -> list[str]:
    """Every document the conditions point to, in order, for the reviewer.

    Most topics link "call document"; EIC topics link the EIC Work Programme, and
    Chips JU topics their own website (16.09.2026), so no one label is reliable.
    """
    return list(
        dict.fromkeys(html.unescape(u) for u in _LINK.findall(topic.get("conditions") or ""))
    )


@register
class EuPortalFetcher(Fetcher):
    slug = "eu-portal"
    listing_is_complete = True  # every page of every scope is read, and counted

    def __init__(self, today: Callable[[], dt.date] | None = None):
        self.today = today or (lambda: dt.datetime.now(dt.UTC).date())

    def unwrap(self, content: bytes, content_type: str | None) -> tuple[bytes, str | None]:
        return render_topic(_topic(content)).encode("utf-8"), "text/html; charset=utf-8"

    def significant(self, content: bytes) -> bytes:
        try:
            data = json.loads(content)
        except ValueError:
            return content
        if isinstance(data, dict) and "TopicDetails" in data:
            try:
                return render_topic(_topic(content)).encode("utf-8")
            except (NormaliseError, KeyError, TypeError, ValueError):
                return content  # an odd topic is compared byte for byte, and reviewed
        if isinstance(data, dict) and "results" in data:
            try:
                page = parse_search(content)
            except ValueError:
                return content
            summary = sorted(
                [
                    _first(r.get("metadata") or {}, "identifier") or "",
                    _first(r.get("metadata") or {}, "status") or "",
                    sorted((r.get("metadata") or {}).get("deadlineDate") or []),
                ]
                for r in page.results
            )
            return json.dumps([page.total, summary]).encode()
        return content

    def crawl(self, ctx: CrawlContext) -> None:
        today = self.today()
        topics: dict[str, dict] = {}
        for scope in SCOPE:
            results: list[dict] = []
            for number in range(1, MAX_PAGES + 1):
                page = parse_search(ctx.fetch(search_request(scope, number)).response.content)
                results.extend(page.results)
                if not page.results or len(results) >= page.total:
                    break
            if page.total == 0:
                # Each scope has had open topics every day since reconnaissance; zero
                # more likely means a changed programme ID than a quiet portal.
                raise ValueError(f"EU search scope {scope.name!r} returned no topics at all")
            if len(results) != page.total:
                raise ValueError(
                    f"EU search scope {scope.name!r}: read {len(results)} of "
                    f"{page.total} results; the listing is incomplete"
                )
            for result in in_scope(results, today):
                topics.setdefault(_first(result["metadata"], "identifier"), result)

        for identifier in sorted(topics):
            metadata = topics[identifier]["metadata"]
            detail = ctx.fetch(topic_request(identifier))
            try:
                links = condition_links(_topic(detail.response.content))
            except NormaliseError:
                links = []  # the pipeline's normaliser reports the broken topic
            ctx.found_call(
                PUBLIC_URL.format(identifier),
                [detail],
                # Unconditional, not only when a link was found: a topic states
                # some of its conditions inline and leaves the rest to the call
                # document or the work programme, and neither is fetched yet
                # (docs/sources.md §6.6). Absence of a link is not evidence the
                # topic is complete, so every EU call carries the gap until those
                # documents are read.
                eligibility_gap=ELIGIBILITY_GAP,
                listing={
                    "identifier": identifier,
                    "call_identifier": _first(metadata, "callIdentifier") or "",
                    "status": _first(metadata, "status") or "",
                    "deadlines": ", ".join(metadata.get("deadlineDate") or []),
                    "condition_links": " ".join(links),
                    "note": "conditions usually point to a call document or work "
                    "programme, which is not extracted yet",
                },
            )
