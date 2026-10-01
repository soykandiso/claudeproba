"""Stage 3 on the worker (roadmap P2 s31): enqueue → outcomes and evidence stored.

The acceptance is proven twice. Once over the evaluation's five frozen calls with
tier B's recorded answers — the whole path from a stored profile row to evidence
rows, on real call text — and once over hand-built calls, where each way a run can
go wrong can be made to happen: a citation that is not where it says, a provider
that is down, a call the rules exclude.
"""

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import delete, func, select

from app.ai.gateway import Gateway
from app.config import load_settings
from app.matching import deep, normalise, verify
from app.models import (
    Account,
    Evidence,
    MatchCriterionOutcome,
    MatchResult,
    MatchRun,
    ModelCall,
    ModelCallPayload,
    RawSnapshot,
    ReviewQueueItem,
)
from app.models.enums import CriterionKind, EntityType, ReviewKind, Verdict
from app.retrieval.embedder import EmbeddingConfig
from app.retrieval.search import Passage, Retrieval
from evals import harness, tier_b
from tests import test_stage1
from tests.test_extract import ScriptedProvider
from tests.test_stage1 import DATABASE_AVAILABLE, NOW, TODAY, hard, make_call

pytestmark = pytest.mark.skipif(not DATABASE_AVAILABLE, reason="no database reachable")

registry = test_stage1.registry

NARRATIVE = (CriterionKind.NARRATIVE_VERIFY, None, None, None)
TEXT = (
    "2.2 Дополнителни услови за претпријатија:\n"
    "Вршат претежна дејност која спаѓа во секторот C - Преработувачка индустрија (10-33.20)"
)
QUOTE = "Вршат претежна дејност која спаѓа во секторот C - Преработувачка индустрија (10-33.20)"
BAKERY = {**test_stage1.COMPANY, "nace": "10.71"}


def reply(**fields) -> str:
    answer = {
        "verdict": "satisfied",
        "confidence": 0.9,
        "passage": 1,
        "quote": QUOTE,
        "reasoning_mk": "Дејноста 10.71 спаѓа во Преработувачката индустрија.",
    }
    answer.update(fields)
    return json.dumps(answer, ensure_ascii=False)


def stored_profile(session, answers, today=TODAY):
    account = Account(email=f"test-{dt.datetime.now().timestamp()}@example.com")
    session.add(account)
    session.flush()
    row = normalise.to_row(normalise.normalise(answers, today), account.id)
    session.add(row)
    session.flush()
    return row.id


# ------------------------------------------------------------------ the stored profile


@pytest.mark.parametrize("key", sorted(harness.load_profiles()))
def test_a_stored_profile_reads_back_as_the_same_profile(key):
    """A report is computed from the row, so the row must be the profile, not a summary."""
    answers = harness.load_profiles()[key].answers
    today = dt.date(2026, 6, 1)
    profile = normalise.normalise(answers, today)

    row = normalise.to_row(profile, account_id=None)

    assert normalise.from_row(row, today) == profile
    # The typed columns hold what is exact, never a band's guessed number.
    assert row.headcount is None and row.investment_size_mkd is None
    assert row.nace_code == profile.nace_code
    assert row.region_code == profile.region_code


def test_a_company_is_stored_as_its_size_band_and_a_trader_as_a_trader():
    company = normalise.to_row(normalise.normalise(test_stage1.COMPANY, TODAY), None)
    trader = normalise.to_row(normalise.normalise({"entity": "tp"}, TODAY), None)
    unsized = normalise.to_row(normalise.normalise({"entity": "doo"}, TODAY), None)

    assert company.entity_type == EntityType.MICRO
    assert trader.entity_type == EntityType.SOLE_TRADER
    assert unsized.entity_type == EntityType.OTHER


# ------------------------------------------------------------------ the frozen calls


@pytest.fixture
def frozen(registry):
    """The five frozen calls as the whole registry, and a clean gateway cache."""
    factory = registry[0]
    fixtures = harness.load_fixtures()
    with factory() as s:
        s.execute(delete(ModelCallPayload))
        s.execute(delete(ModelCall))
        s.execute(delete(ReviewQueueItem))
        calls = harness.load_registry(s, fixtures)
        s.commit()
    return factory, fixtures, calls


def test_a_run_stores_the_verified_top_five_with_their_evidence(frozen):
    """The row's acceptance, over real call text and tier B's recorded answers."""
    factory, fixtures, calls = frozen
    slug_of = {call.id: slug for slug, call in calls.items()}
    key = "p02_bitola_bakery_small"
    provider = tier_b.CassetteProvider(tier_b.load_cassettes(), profile=key)
    fixture_retriever = tier_b.FixtureRetriever(
        {call.id: (call.primary_snapshot_id, fixtures[slug].text) for slug, call in calls.items()}
    )

    def retriever_for(session):
        def retrieve(call, criterion):
            provider.call = slug_of[call.id]  # the cassette answers for this call
            return fixture_retriever(call, criterion)

        return retrieve

    as_of = dt.datetime.combine(harness.load_suite()["as_of"], dt.time(12), dt.UTC)
    with factory() as s:
        profile_id = stored_profile(s, harness.load_profiles()[key].answers, as_of.date())
        s.commit()

    report = deep.run(factory, Gateway(factory, provider), retriever_for, profile_id, as_of)

    with factory() as s:
        run = s.get(MatchRun, report.match_run_id)
        assert run.stage_reached == deep.VERIFIED_STAGE
        assert run.weights_version == "v1" and run.ruleset_version.startswith("ref ")
        assert run.duration_ms is not None and run.candidates_considered >= len(report.ranked)
        stored = s.scalars(
            select(MatchResult).where(MatchResult.match_run_id == run.id).order_by(MatchResult.rank)
        ).all()
        assert [r.rank for r in stored] == list(range(1, len(stored) + 1))
        # The verified calls first, then the calls the rules exclude (P2 s32).
        results = stored[: len(report.ranked)]
        assert 0 < len(results) <= deep.DEPTH
        assert Verdict.NOT_ELIGIBLE not in {r.verdict for r in results}
        assert [r.call_id for r in stored[len(results) :]] == [x.call.id for x in report.excluded]
        assert {r.verdict for r in stored[len(results) :]} <= {Verdict.NOT_ELIGIBLE}
        assert [r.verdict for r in results] == [x.outcome.verdict for x in report.ranked]
        for result, scored in zip(results, report.ranked, strict=True):
            assert set(result.score_breakdown) == {p.name for p in scored.parts}
            outcomes = s.scalars(
                select(MatchCriterionOutcome).where(
                    MatchCriterionOutcome.match_result_id == result.id
                )
            ).all()
            # Every condition of the call has its line, not only the verified ones.
            assert len(outcomes) == len(scored.outcome.outcomes)

        evidence = s.scalars(
            select(Evidence)
            .join(MatchCriterionOutcome, MatchCriterionOutcome.id == Evidence.outcome_id)
            .join(MatchResult, MatchResult.id == MatchCriterionOutcome.match_result_id)
            .where(MatchResult.match_run_id == run.id)
        ).all()
        assert evidence, "the recorded answers cite passages; none was stored"
        for e in evidence:
            text = s.get(RawSnapshot, e.snapshot_id).normalised_text
            assert text[e.char_start : e.char_end] == e.quote
            assert e.source_url.startswith("http")

        # Every model call the run made is counted against it (s36's cost per report).
        model_calls = s.scalars(select(ModelCall)).all()
        assert model_calls and all(m.match_run_id == run.id for m in model_calls)
        assert not s.scalars(select(ReviewQueueItem)).all()


# ------------------------------------------------------------------ hand-built calls


@pytest.fixture
def world(registry):
    factory, source, snapshot = registry
    with factory() as s:
        s.execute(delete(ModelCallPayload))
        s.execute(delete(ModelCall))
        s.execute(delete(ReviewQueueItem))
        # The criteria cite "цитат" at 0–5; the call's text follows it.
        s.get(RawSnapshot, snapshot.id).normalised_text = "цитат\n" + TEXT
        s.commit()
    return factory, source, snapshot


def one_call(world, criteria=(NARRATIVE,)):
    factory, source, snapshot = world
    with factory() as s:
        call = make_call(s, source, snapshot, criteria=list(criteria))
        profile_id = stored_profile(s, BAKERY)
        s.commit()
        return call.id, profile_id


def passage_at(snapshot_id, start):
    def retriever_for(session):
        def retrieve(call, criterion):
            passage = Passage(1, snapshot_id, start, start + len(TEXT), TEXT, 1.0, 1, 1)
            return Retrieval(passages=[passage], unembedded=0, unindexed_snapshots=0)

        return retrieve

    return retriever_for


def evidence_of(factory, run_id):
    with factory() as s:
        return s.scalars(
            select(Evidence)
            .join(MatchCriterionOutcome, MatchCriterionOutcome.id == Evidence.outcome_id)
            .join(MatchResult, MatchResult.id == MatchCriterionOutcome.match_result_id)
            .where(MatchResult.match_run_id == run_id)
        ).all()


def test_a_verified_condition_is_stored_with_the_words_it_rests_on(world):
    factory, _, snapshot = world
    call_id, profile_id = one_call(world)

    report = deep.run(
        factory,
        Gateway(factory, ScriptedProvider(reply())),
        passage_at(snapshot.id, len("цитат\n")),
        profile_id,
        NOW,
    )

    with factory() as s:
        [result] = s.scalars(
            select(MatchResult).where(MatchResult.match_run_id == report.match_run_id)
        )
        assert (result.call_id, result.verdict) == (call_id, Verdict.ELIGIBLE)
        [outcome] = s.scalars(
            select(MatchCriterionOutcome).where(MatchCriterionOutcome.match_result_id == result.id)
        )
        assert (outcome.decided_by, float(outcome.confidence)) == ("model", 0.9)
    [evidence] = evidence_of(factory, report.match_run_id)
    assert evidence.quote == QUOTE
    assert evidence.char_start == len("цитат\n") + TEXT.index(QUOTE)
    assert evidence.source_url == "https://gov.example/call"


def test_evidence_not_at_its_offsets_is_not_stored_and_asks(world):
    """Invariant 2 once more at the last step: the stored text, not the chunk, decides."""
    factory, _, snapshot = world
    _, profile_id = one_call(world)

    # The passage claims to start at 0, so the computed offsets miss the quote by six.
    report = deep.run(
        factory,
        Gateway(factory, ScriptedProvider(reply())),
        passage_at(snapshot.id, 0),
        profile_id,
        NOW,
    )

    assert evidence_of(factory, report.match_run_id) == []
    with factory() as s:
        [verdict] = s.scalars(
            select(MatchResult.verdict).where(MatchResult.match_run_id == report.match_run_id)
        ).all()
        assert verdict == Verdict.NEEDS_VERIFICATION
        [item] = s.scalars(select(ReviewQueueItem)).all()
        assert "not at its offsets" in item.reason
        assert item.match_run_id == report.match_run_id


def test_a_call_the_rules_exclude_is_stored_but_never_verified(world):
    """The report says what the company cannot apply for; no model is asked about it."""
    factory, _, snapshot = world
    excluded = hard("entity_type", "not_in", {"values": ["micro"]})
    call_id, profile_id = one_call(world, criteria=[excluded, NARRATIVE])
    provider = ScriptedProvider()  # any request would fail: there are no replies

    report = deep.run(
        factory, Gateway(factory, provider), passage_at(snapshot.id, 6), profile_id, NOW
    )

    assert provider.requests == []
    assert call_id not in {s.call.id for s in report.ranked}
    assert [s.call.id for s in report.excluded] == [call_id]
    with factory() as s:
        run = s.get(MatchRun, report.match_run_id)
        assert run.stage_reached == deep.VERIFIED_STAGE
        assert run.candidates_considered == 1
        [result] = s.scalars(select(MatchResult).where(MatchResult.match_run_id == run.id))
        assert (result.call_id, result.verdict, result.rank) == (call_id, Verdict.NOT_ELIGIBLE, 1)
    assert evidence_of(factory, report.match_run_id) == []


def test_a_provider_that_fails_leaves_an_unfinished_run_and_no_results(world):
    """No half-verified report is ever stored as if it were finished."""
    factory, _, snapshot = world
    _, profile_id = one_call(world)

    class Down:
        def complete(self, request):
            raise ConnectionError("provider unreachable")

    with pytest.raises(ConnectionError):
        deep.run(factory, Gateway(factory, Down()), passage_at(snapshot.id, 6), profile_id, NOW)

    with factory() as s:
        [run] = s.scalars(select(MatchRun).where(MatchRun.profile_id == profile_id)).all()
        assert run.stage_reached == 2
        count = select(func.count()).select_from(MatchResult)
        assert s.scalar(count.where(MatchResult.match_run_id == run.id)) == 0


def test_the_top_five_only(world):
    factory, source, snapshot = world
    with factory() as s:
        for n in range(deep.DEPTH + 2):
            make_call(s, source, snapshot, title=f"Повик {n}", criteria=[NARRATIVE])
        profile_id = stored_profile(s, BAKERY)
        s.commit()
    provider = ScriptedProvider(*[reply()] * deep.DEPTH)

    report = deep.run(
        factory, Gateway(factory, provider), passage_at(snapshot.id, 6), profile_id, NOW
    )

    # Five identical questions reach the provider once; the gateway's cache answers the rest.
    assert len(provider.requests) == 1
    assert len(report.ranked) == len(report.verified) == deep.DEPTH
    with factory() as s:
        assert s.get(MatchRun, report.match_run_id).candidates_considered == deep.DEPTH + 2


def test_an_unknown_profile_is_an_error_not_an_empty_report(world):
    with pytest.raises(LookupError):
        deep.run(world[0], None, None, uuid.uuid4(), NOW)


# ------------------------------------------------------------------ the queue


def test_enqueue_hands_the_analysis_worker_the_profile(monkeypatch):
    calls = []

    class FakeQueue:
        def __init__(self, name, connection):
            calls.append(("queue", name))

        def enqueue(self, func, *args, **kwargs):
            calls.append(("enqueue", func, args, kwargs["job_timeout"]))
            return type("Job", (), {"id": "job-1"})()

    monkeypatch.setattr("rq.Queue", FakeQueue)
    profile_id = uuid.uuid4()

    assert deep.enqueue(load_settings(), profile_id) == "job-1"
    assert calls == [
        ("queue", "analysis"),
        ("enqueue", deep.job, (str(profile_id),), deep.JOB_TIMEOUT_S),
    ]


def test_the_worker_job_wires_the_production_retriever(world, monkeypatch):
    """`job` builds its own pieces; the real `call_retriever` over an unindexed call
    is an incomplete retrieval, which asks and costs no model call (invariant 3)."""
    factory, _, _ = world
    call_id, profile_id = one_call(world)
    # No verification is asked (see below); the one request is the report's prose.
    provider = ScriptedProvider(
        json.dumps(
            {
                "summary": [
                    {"text_mk": "Условот за дејноста треба да се провери.", "cites": ["1.1"]}
                ],
                "calls": [
                    {
                        "call": 1,
                        "explanation": [
                            {"text_mk": "Текстот на повикот не беше пребаран.", "cites": ["1.1"]}
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )
    )

    class Stub:
        name = "test-embedder"

        def __init__(self, model_dir):
            pass

        def query(self, text):
            return [1.0] * EmbeddingConfig.load().dimensions

    monkeypatch.setattr("app.db.session_factory", lambda settings: factory)
    monkeypatch.setattr("app.ai.gateway.AnthropicProvider", lambda: provider)
    monkeypatch.setattr("app.retrieval.embedder.LocalEmbedder", Stub)

    answer = deep.job(str(profile_id))

    assert answer["calls"] == 1
    # Stage 3 asked nothing: the only request is the composer's.
    assert len(provider.requests) == 1
    assert "paid report" in provider.requests[0].system
    with factory() as s:
        [result] = s.scalars(
            select(MatchResult).where(MatchResult.match_run_id == uuid.UUID(answer["match_run_id"]))
        ).all()
        assert (result.call_id, result.verdict) == (call_id, Verdict.NEEDS_VERIFICATION)
        [outcome] = s.scalars(
            select(MatchCriterionOutcome).where(MatchCriterionOutcome.match_result_id == result.id)
        )
        assert outcome.reason_mk == verify.INCOMPLETE
        item = s.get(ReviewQueueItem, answer["review_item_id"])
        assert item.kind == ReviewKind.REPORT and item.match_run_id == result.match_run_id
