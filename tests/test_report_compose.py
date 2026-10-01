"""The report composer (roadmap P2 s32): prose over a stored run, then the two checks.

The row's acceptance is `test_a_draft_that_says_garantirano_is_blocked`: a model
that writes "гарантирано" produces a draft that is queued, marked blocked, and that
`blockers()` refuses — and so is a clean draft a reviewer edits the word into.
The rest proves citation completeness can fail in each way it names, and that the
whole path runs over the evaluation's frozen calls with every citation resolving.
"""

import copy
import datetime as dt
import json

import pytest
from sqlalchemy import select

from app.ai.gateway import Gateway
from app.matching import deep
from app.models import Call, MatchRun, RawSnapshot, ReviewQueueItem
from app.models.enums import ReviewKind
from app.reports import compose
from evals import harness, tier_b
from tests import test_deep
from tests.test_deep import BAKERY, one_call, passage_at, reply, stored_profile
from tests.test_extract import ScriptedProvider
from tests.test_stage1 import DATABASE_AVAILABLE, NOW

pytestmark = pytest.mark.skipif(not DATABASE_AVAILABLE, reason="no database reachable")

registry = test_deep.registry
world = test_deep.world
frozen = test_deep.frozen

CLEAN = "Условот за дејноста е исполнет според текстот на повикот."


def statement(text=CLEAN, cites=("1.1",)) -> dict:
    return {"text_mk": text, "cites": list(cites)}


def prose(summary=None, calls=None) -> str:
    return json.dumps(
        {
            "summary": summary or [statement()],
            "calls": calls
            or [
                {
                    "call": 1,
                    "explanation": [statement()],
                    "next_steps": [statement("Подгответе ја изјавата пред да аплицирате.")],
                }
            ],
        },
        ensure_ascii=False,
    )


def verified_run(world) -> tuple:
    """One call, its narrative condition verified with evidence at its offsets."""
    factory, _, snapshot = world
    _, profile_id = one_call(world)
    report = deep.run(
        factory,
        Gateway(factory, ScriptedProvider(reply())),
        passage_at(snapshot.id, len("цитат\n")),
        profile_id,
        NOW,
    )
    return factory, report.match_run_id


def composed(factory, run_id, *replies) -> tuple[ReviewQueueItem, ScriptedProvider]:
    provider = ScriptedProvider(*replies)
    item_id = compose.compose(factory, Gateway(factory, provider), run_id)
    with factory() as s:
        return s.get(ReviewQueueItem, item_id), provider


def checks(item) -> set[str]:
    return {p["check"] for p in item.payload["problems"]}


# ------------------------------------------------------------------ the clean path


def test_a_clean_draft_is_queued_for_review_with_nothing_blocking(world):
    factory, run_id = verified_run(world)

    item, provider = composed(factory, run_id, prose())

    assert item.kind == ReviewKind.REPORT and item.match_run_id == run_id
    assert item.payload["problems"] == []
    assert item.priority == compose.PRIORITY_READY
    assert "ready for review" in item.reason
    [call] = item.payload["calls"]
    [condition] = call["conditions"]
    assert condition["ref"] == "1.1" and condition["decided_by"] == "model"
    assert condition["citation"]["quote"] == "цитат"
    assert condition["evidence"]["source_url"] == "https://gov.example/call"
    assert call["explanation"] == [statement()]
    # The model was shown the condition by its number and the applicant as a shape.
    [request] = provider.requests
    assert '<condition number="1.1">' in request.user
    assert BAKERY["municipality"] not in request.user
    with factory() as s:
        assert compose.blockers(s, item) == []


def test_the_draft_is_read_from_the_stored_run_not_recomputed(world):
    """A report read later says what the run found, whatever the registry says now."""
    factory, run_id = verified_run(world)
    with factory() as s:
        draft = compose.load(s, run_id)
        # The call is withdrawn after the run: the draft does not notice.
        call = s.get(Call, draft["calls"][0]["call_id"])
        call.is_published = False
        s.commit()
        assert compose.load(s, run_id) == draft


def test_an_unfinished_run_is_not_composed(world):
    factory, run_id = verified_run(world)
    with factory() as s:
        s.get(MatchRun, run_id).stage_reached = 2
        s.commit()
        with pytest.raises(ValueError):
            compose.load(s, run_id)


# ------------------------------------------------------------------ the lint (the acceptance)


def test_a_draft_that_says_garantirano_is_blocked(world):
    factory, run_id = verified_run(world)
    bad = statement("Финансирањето е гарантирано ако ги исполнувате условите.")

    item, _ = composed(factory, run_id, prose(summary=[bad]))

    assert item.kind == ReviewKind.REPORT  # queued: a person still sees it
    assert checks(item) == {"lint"}
    assert item.priority == compose.PRIORITY_BLOCKED
    assert "blocked" in item.reason
    with factory() as s:
        [problem] = compose.blockers(s, item)
    assert problem["where"] == "summary 1" and "гарантира" in problem["detail"]


def test_a_reviewer_cannot_edit_a_banned_phrase_into_a_clean_draft(world):
    factory, run_id = verified_run(world)
    item, _ = composed(factory, run_id, prose())

    edited = copy.deepcopy(item.payload)
    edited["calls"][0]["next_steps"][0]["text_mk"] = "Ќе добиете грант до крајот на годината."
    with factory() as s:
        item = s.get(ReviewQueueItem, item.id)
        item.corrected_payload = edited
        assert [p["check"] for p in compose.blockers(s, item)] == ["lint"]


def test_verifications_reasons_are_linted_too(world):
    """A reason beside a condition is model Macedonian in the report's own voice."""
    factory, _, snapshot = world
    _, profile_id = one_call(world)
    report = deep.run(
        factory,
        Gateway(factory, ScriptedProvider(reply(reasoning_mk="Условот е одобрено исполнет."))),
        passage_at(snapshot.id, len("цитат\n")),
        profile_id,
        NOW,
    )

    item, _ = composed(factory, report.match_run_id, prose())

    assert [p["where"] for p in item.payload["problems"]] == ["condition 1.1 reason"]


# ------------------------------------------------------------------ citation completeness


@pytest.mark.parametrize(
    ("summary", "calls", "where", "detail"),
    [
        ([statement(cites=["2.1"])], None, "summary 1", "cites 2.1"),
        (
            None,
            [{"call": 1, "explanation": [statement(cites=["1.2"])]}],
            "call 1 explanation 1",
            "cites 1.2",
        ),
        (
            None,
            [{"call": 1, "explanation": [statement()]}, {"call": 2, "explanation": [statement()]}],
            "section for call 2",
            "no such call",
        ),
    ],
)
def test_a_statement_must_cite_a_condition_of_its_own_call(world, summary, calls, where, detail):
    factory, run_id = verified_run(world)

    item, _ = composed(factory, run_id, prose(summary=summary, calls=calls))

    assert checks(item) == {"citation"}
    [problem] = item.payload["problems"]
    assert problem["where"] == where and detail in problem["detail"]


def test_a_statement_that_cites_nothing_is_invalid_output_and_goes_to_review(world):
    """Invariant 5: the schema refuses it, one retry, then the review queue — no draft."""
    factory, run_id = verified_run(world)
    uncited = prose(summary=[statement(cites=[])])

    item, provider = composed(factory, run_id, uncited, uncited)

    assert len(provider.requests) == 2
    assert item.kind == ReviewKind.REPORT and item.match_run_id == run_id
    assert "problems" not in item.payload  # the gateway's record of the failure, not a draft


def test_a_quote_moved_in_the_stored_text_blocks_the_draft(world):
    factory, run_id = verified_run(world)
    snapshot_id = world[2].id
    with factory() as s:
        text = s.get(RawSnapshot, snapshot_id).normalised_text
        s.get(RawSnapshot, snapshot_id).normalised_text = "x" + text
        s.commit()

    item, _ = composed(factory, run_id, prose())

    assert checks(item) == {"citation"}
    assert {p["where"] for p in item.payload["problems"]} == {
        "condition 1.1",
        "condition 1.1 evidence",
    }


def test_a_model_decision_without_its_evidence_blocks_the_draft(world):
    factory, run_id = verified_run(world)
    item, _ = composed(factory, run_id, prose())

    edited = copy.deepcopy(item.payload)
    edited["calls"][0]["conditions"][0]["evidence"] = None
    with factory() as s:
        [problem] = compose.check(s, edited)
    assert (problem["where"], problem["detail"]) == ("condition 1.1 evidence", "no citation")


def test_an_unknown_draft_version_is_refused(world):
    factory, run_id = verified_run(world)
    with factory() as s:
        draft = compose.load(s, run_id)
        draft["version"] = 0
        assert [p["check"] for p in compose.check(s, draft)] == ["version"]


# ------------------------------------------------------------------ the frozen calls


def test_a_report_over_the_frozen_calls_resolves_every_citation(frozen):
    """The whole path on real call text: tier B's answers, then a draft citing every
    condition of every call, and nothing blocking it."""
    factory, fixtures, calls = frozen
    slug_of = {call.id: slug for slug, call in calls.items()}
    key = "p02_bitola_bakery_small"
    provider = tier_b.CassetteProvider(tier_b.load_cassettes(), profile=key)
    fixture_retriever = tier_b.FixtureRetriever(
        {call.id: (call.primary_snapshot_id, fixtures[slug].text) for slug, call in calls.items()}
    )

    def retriever_for(session):
        def retrieve(call, criterion):
            provider.call = slug_of[call.id]
            return fixture_retriever(call, criterion)

        return retrieve

    as_of = dt.datetime.combine(harness.load_suite()["as_of"], dt.time(12), dt.UTC)
    with factory() as s:
        profile_id = stored_profile(s, harness.load_profiles()[key].answers, as_of.date())
        s.commit()
    report = deep.run(factory, Gateway(factory, provider), retriever_for, profile_id, as_of)

    with factory() as s:
        draft = compose.load(s, report.match_run_id)
    assert len(draft["calls"]) == len(report.ranked)
    assert len(draft["excluded"]) == len(report.excluded)
    for entry in draft["excluded"]:
        assert entry["conditions"] and {c["decided_by"] for c in entry["conditions"]} == {"rule"}
    refs = [[c["ref"] for c in call["conditions"]] for call in draft["calls"]]
    written = prose(
        summary=[statement(cites=[r[0] for r in refs])],
        calls=[
            # Every condition cited, at most eight per statement (the schema's limit).
            {"call": n, "explanation": [statement(cites=r[i : i + 8]) for i in range(0, len(r), 8)]}
            for n, r in enumerate(refs, 1)
        ],
    )

    item, _ = composed(factory, report.match_run_id, written)

    assert item.payload["problems"] == []
    # Every condition in the draft carries a citation that was found in the stored text.
    conditions = [c for call in draft["calls"] + draft["excluded"] for c in call["conditions"]]
    assert conditions and all(c["citation"]["retrieved_at"] for c in conditions)
    assert any(c["evidence"] for c in conditions)
    with factory() as s:
        assert s.scalars(select(ReviewQueueItem).where(ReviewQueueItem.id == item.id)).one()
