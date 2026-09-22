"""Stage 3's verification pass (roadmap P2 s29), against scripted model replies.

The acceptance names one failure above all: **a paraphrased "quote" is rejected**.
The rest are the other gates of docs/matching.md §5 — invalid output, a passage
that does not exist, low confidence, a retrieval that did not search everything —
and the two invariants a model could otherwise break: it never excludes anyone, and
it never sees who the applicant is.
"""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.ai.gateway import Gateway
from app.ai.schemas import VerificationResult
from app.matching import stage1, verify
from app.models import ModelCall, ModelCallPayload, ReviewQueueItem
from app.models.enums import CriterionKind, ReviewKind, Verdict
from app.retrieval.search import Passage, Retrieval
from tests import test_stage1
from tests.test_extract import ScriptedProvider
from tests.test_stage1 import DATABASE_AVAILABLE, NOW, make_call, profile

pytestmark = pytest.mark.skipif(not DATABASE_AVAILABLE, reason="no database reachable")

registry = test_stage1.registry

TEXT = (
    "2.2 Дополнителни услови за претпријатија:\n"
    "Вршат претежна дејност која спаѓа во секторот C - Преработувачка индустрија (10-33.20)\n"
    "Имаат минимум 2 (двајца) вработени на неопределено работно време."
)
QUOTE = "Вршат претежна дејност која спаѓа во секторот C - Преработувачка индустрија (10-33.20)"
NARRATIVE = (CriterionKind.NARRATIVE_VERIFY, None, None, None)


def passages(text=TEXT, complete=True):
    def retrieve(call, query):
        return Retrieval(
            passages=[Passage(1, 42, 100, 100 + len(text), text, 1.0, 1, 1)],
            unembedded=0 if complete else 3,
            unindexed_snapshots=0,
        )

    return retrieve


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


@pytest.fixture
def world(registry):
    factory, source, snapshot = registry
    with factory() as s:
        # A scripted reply must not be answered from the gateway's content-hash
        # cache of an earlier run (handoff §5), and review items are counted.
        s.execute(delete(ModelCallPayload))
        s.execute(delete(ModelCall))
        s.execute(delete(ReviewQueueItem))
        s.commit()
    return factory, source, snapshot


def run(world, provider, *, criteria=(NARRATIVE,), retrieve=None, applicant=None):
    factory, source, snapshot = world
    p = applicant or profile(nace="10.71")
    with factory() as s:
        make_call(s, source, snapshot, criteria=list(criteria))
        s.commit()
        [outcome] = stage1.run(s, p, NOW)
        s.commit()
    # Outside that session: closing it would roll back the savepoint the review
    # items are committed into, and the test would find none.
    return verify.verify_call(
        Gateway(factory, provider), factory, retrieve or passages(), p, outcome
    )


def review_items(factory):
    with factory() as s:
        return s.scalars(select(ReviewQueueItem)).all()


# ------------------------------------------------------------------ the gates


def test_a_verbatim_quote_decides_and_is_located_in_the_stored_text(world):
    outcome, [verified] = run(world, ScriptedProvider(reply()))

    assert verified.outcome.verdict == Verdict.ELIGIBLE
    assert outcome.verdict == Verdict.ELIGIBLE
    evidence = verified.evidence
    assert (evidence.snapshot_id, evidence.quote) == (42, QUOTE)
    assert evidence.char_start == 100 + TEXT.index(QUOTE)
    assert evidence.char_end - evidence.char_start == len(QUOTE)


def test_a_paraphrased_quote_is_rejected_and_goes_to_a_person(world):
    """The acceptance of the row: the words must be the call's, not the model's."""
    paraphrase = "Претежната дејност треба да е во преработувачката индустрија (10-33)"
    factory = world[0]

    outcome, [verified] = run(world, ScriptedProvider(reply(quote=paraphrase)))

    assert verified.outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert verified.outcome.reason_mk == verify.UNVERIFIABLE
    assert verified.evidence is None
    assert outcome.verdict == Verdict.NEEDS_VERIFICATION
    [item] = review_items(factory)
    assert item.kind == ReviewKind.VERIFICATION
    assert "not in passage 1" in item.reason
    assert item.payload["answer"]["quote"] == paraphrase


def test_a_passage_the_model_was_not_shown_is_rejected(world):
    outcome, [verified] = run(world, ScriptedProvider(reply(passage=4)))

    assert verified.outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert "passage 4 of 1 does not exist" in review_items(world[0])[0].reason


def test_a_model_never_excludes_anyone(world):
    """Invariant 1: not_satisfied from a model is 'check this', not 'you may not'."""
    outcome, [verified] = run(world, ScriptedProvider(reply(verdict="not_satisfied")))

    assert verified.outcome.decision.outcome.value == "not_satisfied"
    assert verified.outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert verified.evidence is not None  # the reason is still shown, with its words


def test_low_confidence_keeps_the_evidence_and_decides_nothing(world):
    outcome, [verified] = run(world, ScriptedProvider(reply(confidence=0.6)))

    assert verified.outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert verified.evidence.confidence == 0.6
    assert review_items(world[0]) == []


def test_invalid_output_twice_goes_to_review_and_asks(world):
    outcome, [verified] = run(world, ScriptedProvider("not json", '{"verdict": "maybe"}'))

    assert verified.outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert verified.outcome.reason_mk == verify.INVALID
    [item] = review_items(world[0])
    assert item.kind == ReviewKind.VERIFICATION and item.id == verified.review_item_id


def test_an_incomplete_retrieval_is_a_failed_one_and_costs_nothing(world):
    provider = ScriptedProvider()
    outcome, [verified] = run(world, provider, retrieve=passages(complete=False))

    assert verified.outcome.reason_mk == verify.INCOMPLETE
    assert verified.outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert provider.requests == []


def test_a_call_the_rules_exclude_is_not_sent_to_the_model(world):
    provider = ScriptedProvider()
    excludes = test_stage1.hard("entity_type", "in", {"values": ["large"]})

    outcome, verified = run(world, provider, criteria=[excludes, NARRATIVE])

    assert outcome.verdict == Verdict.NOT_ELIGIBLE and verified == []
    assert provider.requests == []


# ------------------------------------------------------------------ attestations

ATTEST = (CriterionKind.APPLICANT_ATTEST, None, None, None)
RESIDENCE = "Занаетчии, жители на град Скопје"
SKOPJE_TEXT = f"2.1 Право на учество имаат:\n- {RESIDENCE} ( во општините: Аеродром, Карпош)"


def test_an_attestation_the_profile_contradicts_asks_instead_of_likely(world):
    """The Bitola craftsman and the Skopje-only subsidy (tier B, s29)."""
    answer = reply(verdict="not_satisfied", quote=RESIDENCE, reasoning_mk="Седиштето е во Битола.")

    outcome, [verified] = run(
        world, ScriptedProvider(answer), criteria=[ATTEST], retrieve=passages(SKOPJE_TEXT)
    )

    assert verified.outcome.verdict == Verdict.NEEDS_VERIFICATION
    assert outcome.verdict == Verdict.NEEDS_VERIFICATION


@pytest.mark.parametrize(
    "answer",
    [
        reply(verdict="satisfied", quote=RESIDENCE),
        reply(verdict="not_satisfied", quote=RESIDENCE, confidence=0.5),
        reply(verdict="not_satisfied", quote="Жители на Скопје и околината"),  # paraphrase
    ],
)
def test_a_model_never_confirms_an_attestation_and_a_doubt_changes_nothing(world, answer):
    """Only the applicant confirms: satisfied, unsure or unverifiable, it stays theirs."""
    outcome, [verified] = run(
        world, ScriptedProvider(answer), criteria=[ATTEST], retrieve=passages(SKOPJE_TEXT)
    )

    assert verified.outcome.verdict == Verdict.LIKELY_ELIGIBLE
    assert outcome.verdict == Verdict.LIKELY_ELIGIBLE


# ------------------------------------------------------------------ what leaves


def test_the_model_sees_the_applicants_shape_and_nothing_that_names_it(world):
    """Invariant 4. The founding year and municipality narrow a register search; bands do not."""
    provider = ScriptedProvider(reply())
    applicant = profile(nace="10.71", description="Пекара Јовановски, тел. 070 123 456")

    run(world, provider, applicant=applicant)

    sent = provider.requests[0].user
    assert "10.71" in sent and "Скопски" in sent and "2–9" in sent
    assert "Седиште во Град Скопје: да" in sent
    for leak in ("Јовановски", "070 123 456", "2022", "Центар"):
        assert leak not in sent


# ------------------------------------------------------------------ the schema


@pytest.mark.parametrize(
    "answer",
    [
        {"verdict": "satisfied", "confidence": 0.9, "reasoning_mk": "Без цитат, без тврдење."},
        {"verdict": "unclear", "confidence": 0.4, "passage": 1, "reasoning_mk": "Половина цитат."},
    ],
)
def test_a_decision_without_its_words_is_not_a_valid_answer(answer):
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(answer)


def test_unclear_may_come_back_without_a_quote():
    answer = VerificationResult.model_validate(
        {"verdict": "unclear", "confidence": 0.3, "reasoning_mk": "Профилот не кажува доволно."}
    )
    assert answer.quote is None


def test_the_routed_prompt_exists_and_takes_exactly_what_verify_supplies():
    """A prompt is a versioned file (CLAUDE.md); a missing variable must fail here, not in a run."""
    from app.ai.gateway import DEFAULT_PROMPTS, Routing
    from app.ai.prompts import load_prompt

    route = Routing.load().route(verify.TASK)
    prompt = load_prompt(DEFAULT_PROMPTS, verify.TASK, route.prompt_version)
    system, user = prompt.render(
        {"criterion": "У", "criterion_quote": "Ц", "applicant": "- А", "passages": "П"}
    )
    assert route.model == "claude-opus-5"
    assert "$" not in system + user
