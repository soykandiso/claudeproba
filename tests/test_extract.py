"""extract_call through the real gateway, prompt file and routing, against PostgreSQL.

Roadmap P1 s10 acceptance: on three real fixtures, criteria extract with
citations; a malformed response lands in the review queue. The provider is
scripted with the hand-written replies in tests/cassettes/extract_call/.
"""

import json

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.ai.gateway import Gateway, InvalidModelOutput, ProviderReply
from app.config import load_settings
from app.ingestion.extract import TASK, Document, extract_call
from app.models import ModelCall, ModelCallPayload, ReviewQueueItem
from app.models.enums import ReviewKind
from tests.test_extract_schema import CASES, cassette, fixture_text
from tests.test_gateway import DATABASE_AVAILABLE

settings = load_settings()

pytestmark = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)


class ScriptedProvider:
    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ProviderReply(
            text=self.replies.pop(0), stop_reason="end_turn", input_tokens=4000, output_tokens=900
        )


@pytest.fixture
def session_factory():
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    with factory() as s:
        # Real runs leave audit rows and review items in the development database;
        # these tests count them, so they start from none (all rolled back below).
        s.execute(delete(ModelCallPayload))
        s.execute(delete(ModelCall))
        s.execute(delete(ReviewQueueItem))
        s.commit()
    yield factory
    transaction.rollback()
    connection.close()
    engine.dispose()


def documents(name: str) -> list[Document]:
    return [Document(snapshot_id=7, url=f"https://example.mk/{name}", text=fixture_text(name))]


def review_items(session_factory):
    with session_factory() as s:
        return s.scalars(select(ReviewQueueItem).order_by(ReviewQueueItem.id)).all()


@pytest.mark.parametrize("name", CASES)
def test_a_fixture_extracts_with_every_criterion_cited(session_factory, name):
    provider = ScriptedProvider(cassette(name))
    gateway = Gateway(session_factory, provider)
    docs = documents(name)

    extraction = extract_call(gateway, session_factory, docs)

    assert extraction.ok and extraction.review_item_id is None
    assert review_items(session_factory) == []
    for index in range(len(extraction.output.criteria)):
        citation = extraction.citations[f"criteria.{index}"]
        assert docs[0].text[citation.char_start : citation.char_end] == citation.source_quote
    with session_factory() as s:
        row = s.get(ModelCall, extraction.model_call_id)
        assert row.ok and row.prompt_version_id.startswith(f"{TASK}/")


def test_the_documents_sent_carry_no_contact_data(session_factory):
    provider = ScriptedProvider(cassette("ipard-notice-03-2025"))

    extract_call(
        Gateway(session_factory, provider), session_factory, documents("ipard-notice-03-2025")
    )

    sent = provider.requests[0].user
    assert "ipardpa.info@ipardpa.gov.mk" not in sent and "3097-460" not in sent
    assert "[EMAIL_1]" in sent and "Мерка 7" in sent


def test_a_malformed_response_lands_in_the_review_queue(session_factory):
    """A criterion that could wrongly exclude applicants is malformed, however well it parses."""
    reply = json.loads(cassette("economy-call-3"))
    conditional = next(c for c in reply["criteria"] if not c["applies_to_all_applicants"])
    conditional |= {
        "kind": "hard_structured",
        "field": "headcount",
        "operator": "gte",
        "minimum": 2,
    }
    provider = ScriptedProvider(json.dumps(reply), json.dumps(reply))

    with pytest.raises(InvalidModelOutput) as raised:
        extract_call(
            Gateway(session_factory, provider), session_factory, documents("economy-call-3")
        )

    assert len(provider.requests) == 2
    assert "only some applicant types" in provider.requests[1].user
    [item] = review_items(session_factory)
    assert item.id == raised.value.review_item_id and item.kind == ReviewKind.EXTRACTION


def test_an_invented_quote_sends_the_whole_extraction_to_review(session_factory):
    reply = json.loads(cassette("av-measure-819"))
    reply["criteria"][0]["quote"] = "Право на учество имаат само приватни работодавачи"
    provider = ScriptedProvider(json.dumps(reply))

    extraction = extract_call(
        Gateway(session_factory, provider), session_factory, documents("av-measure-819")
    )

    assert not extraction.ok
    assert "criteria.0" not in extraction.citations
    [item] = review_items(session_factory)
    assert item.id == extraction.review_item_id
    assert item.payload["stage"] == "extract" and item.payload["snapshot_ids"] == [7]
    assert [f["path"] for f in item.payload["failures"]] == ["criteria.0"]
    assert item.payload["extraction"]["criteria"][0]["quote"].startswith("Право на учество")
