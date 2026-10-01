"""The AV fetcher's parsing, against the responses captured in reconnaissance."""

import json
from pathlib import Path

import pytest

from app.ingestion.normalise import NormaliseError, normalise
from app.ingestion.sources import fetchers
from app.ingestion.sources.av import AvFetcher, detail_request, open_business_announcements
from tests.test_extract_schema import fixture_text

FIXTURES = Path(__file__).parent / "fixtures" / "av"


def listing(changes: dict[int, dict] | None = None) -> bytes:
    """The captured archive, with some announcements' fields changed."""
    data = json.loads((FIXTURES / "measures-list.json").read_bytes())
    for item in data["d"]:
        item.update((changes or {}).get(item["AnnouncementId"], {}))
    return json.dumps(data).encode()


def test_the_fetcher_is_registered():
    assert fetchers()["av"] is AvFetcher and AvFetcher.listing_is_complete


def test_only_open_announcements_for_legal_entities_are_fetched():
    open_ids = [item["AnnouncementId"] for item in open_business_announcements(listing())]
    assert open_ids == [813]  # 13.09.2026: the one active call with a text for employers

    reopened = listing({819: {"ActiveMeasureIsArchived": False}})
    assert 819 in [item["AnnouncementId"] for item in open_business_announcements(reopened)]

    # 829 is for individuals only (PbBusinessDescriptionMKD 0).
    individuals = listing({829: {"ActiveMeasureIsArchived": False}})
    assert 829 not in [item["AnnouncementId"] for item in open_business_announcements(individuals)]


@pytest.mark.parametrize("body", [b'{"d": []}', b"<html>maintenance</html>", b'{"d": "x"}'])
def test_a_broken_listing_fails_the_crawl_instead_of_looking_quiet(body):
    with pytest.raises(ValueError):
        open_business_announcements(body)


def test_the_detail_request_is_the_same_bytes_on_every_run():
    request = detail_request(819)
    assert request.body == b'{"detailId":819}' and request.method == "POST"
    assert request.identity.endswith(
        'GetActiveEmploymentMeasureDescriptionForBusinessMk#POST {"detailId":819}'
    )


def test_unwrap_gives_the_normaliser_the_call_text():
    content, content_type = AvFetcher().unwrap(
        (FIXTURES / "measure-819-business-mk.json").read_bytes(), "application/json; charset=utf-8"
    )
    assert normalise(content, content_type).text == fixture_text("av-measure-819")


@pytest.mark.parametrize("body", [b'{"d": ""}', b'{"d": null}', b"{}", b"not json"])
def test_an_unexpected_description_is_a_normalise_error(body):
    with pytest.raises(NormaliseError):
        AvFetcher().unwrap(body, "application/json")
