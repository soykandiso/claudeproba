"""The LLM gateway against a real PostgreSQL, with a scripted provider.

No test here reaches a real model. The provider is replaced by a script of
replies, which is what makes the failure paths testable at all.
"""

import re
from pathlib import Path

import psycopg
import pytest
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.ai.gateway import (
    Gateway,
    InvalidModelOutput,
    PromptChanged,
    ProviderReply,
    Route,
    Routing,
)
from app.ai.scrub import IdentityLeak
from app.config import load_settings
from app.models import ModelCall, ModelCallPayload, ReviewQueueItem
from app.models.enums import ReviewKind

settings = load_settings()

try:
    with psycopg.connect(settings.database_url, connect_timeout=2):
        DATABASE_AVAILABLE = True
except Exception:
    DATABASE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DATABASE_AVAILABLE, reason="no database reachable; start `docker compose up -d`"
)

TASK = "summarise_test"
VERSION = "2026-09-13.1"

PROMPT = """\
Return the call's deadline and maximum grant as JSON.

<!-- user -->
Applicant: $applicant
Call text:
$call_text
"""


class Summary(BaseModel):
    deadline: str = Field(pattern=r"^\d{2}\.\d{2}\.\d{4}$")
    max_grant_mkd: int = Field(ge=0)


VALID = '{"deadline": "30.09.2026", "max_grant_mkd": 200000}'
INVALID = '{"deadline": "September 30", "max_grant_mkd": "a lot"}'


class ScriptedProvider:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text, stop_reason = reply if isinstance(reply, tuple) else (reply, "end_turn")
        return ProviderReply(
            text=text, stop_reason=stop_reason, input_tokens=1200, output_tokens=40
        )


@pytest.fixture
def session_factory():
    """Everything the gateway commits becomes a savepoint inside one rolled-back transaction."""
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    yield sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def prompts_dir(tmp_path) -> Path:
    # Rows from each test are rolled back, so every test sees this file as never run.
    (tmp_path / TASK).mkdir()
    (tmp_path / TASK / f"{VERSION}.md").write_text(PROMPT, encoding="utf-8")
    return tmp_path


def make_gateway(session_factory, prompts_dir, provider):
    routing = Routing(
        tasks={TASK: Route(model="claude-opus-5", prompt_version=VERSION)},
        pricing={"claude-opus-5": (5.0, 25.0)},
    )
    return Gateway(session_factory, provider, routing=routing, prompts_dir=prompts_dir)


def run(gateway, call_text="Рок: 30.09.2026. Максимум 200.000 денари."):
    return gateway.run(
        TASK,
        variables={
            "applicant": "Бетон Градба ДООЕЛ, contact marija@betongradba.mk, +389 70 123 456",
            "call_text": call_text,
        },
        known_identifiers=["Бетон Градба ДООЕЛ"],
        response_model=Summary,
        on_invalid=ReviewKind.EXTRACTION,
    )


def calls(session_factory):
    with session_factory() as s:
        return s.scalars(select(ModelCall).order_by(ModelCall.id)).all()


def test_a_valid_reply_is_returned_and_audited(session_factory, prompts_dir):
    gateway = make_gateway(session_factory, prompts_dir, ScriptedProvider(VALID))

    result = run(gateway)

    assert result.output == Summary(deadline="30.09.2026", max_grant_mkd=200000)
    assert not result.cache_hit
    [row] = calls(session_factory)
    assert row.ok and row.model == "claude-opus-5" and row.prompt_version_id == f"{TASK}/{VERSION}"
    assert float(row.cost_usd) == pytest.approx((1200 * 5 + 40 * 25) / 1_000_000)


def test_what_left_the_building_carries_no_identity_data(session_factory, prompts_dir):
    provider = ScriptedProvider(VALID)
    run(make_gateway(session_factory, prompts_dir, provider))

    sent = provider.requests[0].system + provider.requests[0].user
    with session_factory() as s:
        stored = s.scalars(select(ModelCallPayload)).one().request_json

    for value in ["Бетон Градба", "marija@betongradba.mk", "70 123 456"]:
        assert value not in sent
        assert value not in str(stored)
    assert "[IDENTIFIER_1]" in sent and "[EMAIL_1]" in sent


def test_invalid_twice_fails_closed_into_the_review_queue(session_factory, prompts_dir):
    """Roadmap P1 s7 acceptance: a deliberately invalid response never publishes."""
    provider = ScriptedProvider(INVALID, INVALID)
    gateway = make_gateway(session_factory, prompts_dir, provider)

    with pytest.raises(InvalidModelOutput) as raised:
        run(gateway)

    assert len(provider.requests) == 2, "exactly one retry"
    assert "rejected" in provider.requests[1].user, "the retry carries the validation errors"
    assert [row.ok for row in calls(session_factory)] == [False, False]
    with session_factory() as s:
        item = s.get(ReviewQueueItem, raised.value.review_item_id)
        assert item.kind == ReviewKind.EXTRACTION
        assert item.state == "pending"
        assert len(item.payload["model_call_ids"]) == 2


def test_one_retry_can_recover(session_factory, prompts_dir):
    gateway = make_gateway(session_factory, prompts_dir, ScriptedProvider(INVALID, VALID))

    assert run(gateway).output.max_grant_mkd == 200000
    assert [row.ok for row in calls(session_factory)] == [False, True]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_a_refused_or_truncated_reply_is_not_accepted_even_if_it_parses(
    session_factory, prompts_dir, stop_reason
):
    provider = ScriptedProvider((VALID, stop_reason), (VALID, stop_reason))

    with pytest.raises(InvalidModelOutput):
        run(make_gateway(session_factory, prompts_dir, provider))


def test_an_unchanged_input_is_answered_from_cache(session_factory, prompts_dir):
    provider = ScriptedProvider(VALID)
    gateway = make_gateway(session_factory, prompts_dir, provider)

    run(gateway)
    second = run(gateway)

    assert second.cache_hit
    assert len(provider.requests) == 1, "the second run spent no tokens"
    assert [row.cache_hit for row in calls(session_factory)] == [False, True]


def test_a_changed_input_is_not_answered_from_cache(session_factory, prompts_dir):
    provider = ScriptedProvider(VALID, VALID)
    gateway = make_gateway(session_factory, prompts_dir, provider)

    run(gateway)
    run(gateway, call_text="Рок: 30.09.2026. Максимум 250.000 денари.")

    assert len(provider.requests) == 2


def test_a_prompt_edited_after_running_is_refused(session_factory, prompts_dir):
    gateway = make_gateway(session_factory, prompts_dir, ScriptedProvider(VALID))
    run(gateway)

    path = prompts_dir / TASK / f"{VERSION}.md"
    path.write_text(PROMPT.replace("deadline", "closing date"), encoding="utf-8")

    with pytest.raises(PromptChanged):
        run(gateway)


def test_identity_data_in_the_prompt_file_itself_never_leaves(session_factory, prompts_dir):
    """The tripwire checks the rendered prompt, not only the inputs."""
    path = prompts_dir / TASK / f"{VERSION}.md"
    path.write_text(PROMPT.replace("as JSON.", "as JSON. Questions: help@example.mk"))
    provider = ScriptedProvider(VALID)

    with pytest.raises(IdentityLeak):
        run(make_gateway(session_factory, prompts_dir, provider))

    assert provider.requests == []


def test_a_provider_outage_is_recorded_and_raised_not_reviewed(session_factory, prompts_dir):
    provider = ScriptedProvider(ConnectionError("provider unreachable"))

    with pytest.raises(ConnectionError):
        run(make_gateway(session_factory, prompts_dir, provider))

    [row] = calls(session_factory)
    assert not row.ok and re.match(r"provider error", row.validation_error)
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(ReviewQueueItem)) == 0
