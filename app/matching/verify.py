"""Stage 3: a model reads the call's own words for the conditions no rule can decide.

docs/matching.md §5. For one call, each approved `narrative_verify` criterion is
checked against passages retrieved from the call's documents, and the answer is
admitted only through three gates, in this order:

1. **The output is valid** — the gateway validates `VerificationResult`, retries
   once, and on a second failure sends it to the review queue. Here that is an
   undecided criterion, never a guess (invariant 5).
2. **The quote is in the passage it names**, character for character, found in
   code. A paraphrase dressed as a quotation goes to a human and the criterion
   stays undecided (invariant 2). This is the gate a paying customer is protected
   by: an invented citation otherwise looks exactly like a real one.
3. **Confidence of at least 0.7**, or the answer is kept as evidence and the
   criterion stays undecided.

What survives is clamped into the customer's vocabulary by `taxonomy`: a model's
`satisfied` counts, its `not_satisfied` becomes *needs verification*, never *not
eligible* — the model cannot exclude anyone (invariant 1). Retrieval that did not
search everything counts as a failed retrieval (invariant 3).

**The applicant goes as a shape**, never an identity (invariant 4): form and size
band, activity code, region, age, headcount and investment bands — nothing a
person could be found by. The gateway scrubs again on the way out.

**Retrieval is passed in.** Production uses `call_retriever`, `hybrid_retrieve`
over the call's current documents; the evaluation's tier B uses a deterministic
retriever over the frozen document, because what it measures is this module and
the prompt. Retrieval itself is measured by `evals/run.py --retrieval` (P2 s30).

**What is searched for is the criterion's own words, and where they are is not
searched for at all.** The chunk holding the cited span is pinned first; the query
is the source quote, which fills the other passages with what reads like it. The
design sketched `label_mk + ' ' + source_quote`; measured over the frozen calls
(P2 s30), the label only lowered the quote's trigram score — below the threshold
for an English quote under a Macedonian label — and found nothing the quote alone
did not.

**Attestations are read too, and can only go down.** A condition only the
applicant can confirm ("resident in one of the ten municipalities of Град Скопје",
"an employee on a permanent contract for six months") is outstanding until they
confirm it — but the profile may already answer it, and answer it no. Left alone,
a Bitola craftsman is shown a Skopje-only subsidy as "likely eligible" the moment
the craft itself is verified. So an attestation is checked like a narrative
condition, and a clear, cited `not_satisfied` turns it into *needs verification*.
Nothing else changes it: a model may find an attestation contradicted, never
confirm one, and never exclude on it. Found by the evaluation's tier B (P2 s29),
which is also where the AV over-claims of s26 went.

`documentary` criteria are not verified here: a document is something the
applicant brings, so stage 1 treats it like an attestation (`stage1._decide`).
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from app.ai.gateway import Gateway, InvalidModelOutput
from app.ai.schemas import VerificationResult
from app.matching import intake, stage1
from app.matching.normalise import TURNOVER_BANDS, Profile
from app.matching.stage1 import CallOutcome, CriterionOutcome
from app.matching.taxonomy import DecidedBy, Decision, Outcome, criterion_verdict
from app.models import Call, EligibilityCriterion, ReviewQueueItem
from app.models.enums import CriterionKind, ReviewKind, Verdict
from app.retrieval.embedder import Embedder
from app.retrieval.search import Passage, Retrieval, call_snapshot_ids, hybrid_retrieve

TASK = "verify_criterion"

# Below this the answer is kept as evidence but decides nothing (matching.md §5).
MIN_CONFIDENCE = 0.7

# Reasons the customer reads beside a condition that stayed undecided.
INCOMPLETE = "Текстот на повикот не беше целосно пребаран, па условот треба да се провери."
INVALID = "Автоматската проверка не даде валиден одговор; условот го проверува уредник."
UNVERIFIABLE = (
    "Цитатот од автоматската проверка не е пронајден во текстот на повикот; "
    "условот го проверува уредник."
)

# How many passages the model is shown for one criterion (matching.md §5).
PASSAGES = 6

# (call, criterion) -> the passages to show the model, and whether everything was searched.
Retriever = Callable[[Call, EligibilityCriterion], Retrieval]


def query_for(criterion: EligibilityCriterion) -> str:
    """The criterion's quoted words; the label only if it somehow has none."""
    return (criterion.source_quote or criterion.label_mk).strip()


def cited_span(criterion: EligibilityCriterion) -> tuple[int, int, int] | None:
    if criterion.snapshot_id is None or criterion.quote_start is None:
        return None
    return criterion.snapshot_id, criterion.quote_start, criterion.quote_end


def call_retriever(session: Session, embedder: Embedder, *, k: int = PASSAGES) -> Retriever:
    """The production retriever: a call's current documents, the cited chunk first."""

    def retrieve(call: Call, criterion: EligibilityCriterion) -> Retrieval:
        return hybrid_retrieve(
            session,
            embedder,
            call_snapshot_ids(session, call.id),
            query_for(criterion),
            k=k,
            pin=cited_span(criterion),
        )

    return retrieve


@dataclass(frozen=True)
class Evidence:
    """The words a model's answer rests on, located in the stored text by code."""

    snapshot_id: int
    char_start: int
    char_end: int
    quote: str
    confidence: float
    verdict: str
    reasoning_mk: str
    model_call_id: int


@dataclass(frozen=True)
class Verified:
    outcome: CriterionOutcome
    evidence: Evidence | None = None
    review_item_id: int | None = None


# ------------------------------------------------------------------ the payload


def applicant_shape(profile: Profile) -> str:
    """The applicant as the model may see it: bands and codes, one per line.

    The municipality is left out on purpose — the design's list stops at the
    region (docs/matching.md §5, CLAUDE.md invariant 4) — and so is the project
    description, which is free text and not needed to read a condition.
    """
    age = profile.age_months
    rows = [
        ("Вид на субјект", intake.entity_label(profile)),
        (
            "Дејност",
            f"{profile.nace.code} {profile.nace.name_mk}" if profile.nace else None,
        ),
        ("Регион", intake.region_label(profile)),
        # Град Скопје funds ten municipalities, not the Skopje region; one yes or no
        # lets a model read such a condition without the municipality itself.
        (
            "Седиште во Град Скопје",
            ("да" if profile.in_city_of_skopje else "не") if profile.municipality else None,
        ),
        # Months, not the founding year: a band is a shape, a year narrows a register search.
        ("Старост", f"{int(age.lo)}–{int(age.hi)} месеци" if age else None),
        ("Вработени", intake.employees_label(profile)),
        ("Годишен промет", intake.band_label(TURNOVER_BANDS, profile, "turnover")),
        ("Износ на инвестицијата", intake.amount_label(profile)),
    ]
    return "\n".join(f"- {label}: {value or 'не е наведено'}" for label, value in rows)


def render_passages(passages: list[Passage]) -> str:
    return "\n\n".join(
        f'<passage number="{n}">\n{p.text}\n</passage>' for n, p in enumerate(passages, 1)
    )


# ------------------------------------------------------------------ one criterion


def _undecided(item: CriterionOutcome, reason: str) -> CriterionOutcome:
    unclear = Decision(Outcome.UNCLEAR, DecidedBy.MODEL)
    return replace(item, decision=unclear, verdict=criterion_verdict(unclear), reason_mk=reason)


def _decided(item: CriterionOutcome, verdict: str, reason: str) -> CriterionOutcome:
    outcome = {
        "satisfied": Outcome.SATISFIED,
        "not_satisfied": Outcome.NOT_SATISFIED,
    }.get(verdict, Outcome.UNCLEAR)
    decision = Decision(outcome, DecidedBy.MODEL)
    # criterion_verdict is the clamp: NOT_SATISFIED decided by a model is
    # needs_verification there, whatever the model meant.
    return replace(item, decision=decision, verdict=criterion_verdict(decision), reason_mk=reason)


def _review(session_factory, call: Call, criterion, result, passages, why: str) -> int:
    # Its own transaction, like extraction's: the record survives a caller that rolls back.
    with session_factory() as session:
        item = ReviewQueueItem(
            kind=ReviewKind.VERIFICATION,
            reason=f"{TASK}: {why}",
            call_id=call.id,
            payload={
                "stage": "verify",
                "criterion_id": str(criterion.id),
                "criterion": criterion.label_mk,
                "model_call_id": result.model_call_id,
                "answer": result.output.model_dump(mode="json"),
                "passages": [
                    {"number": n, "snapshot_id": p.snapshot_id, "char_start": p.char_start}
                    for n, p in enumerate(passages, 1)
                ],
            },
        )
        session.add(item)
        session.commit()
        return item.id


def verify_criterion(
    gateway: Gateway,
    session_factory,
    retrieve: Retriever,
    profile: Profile,
    call: Call,
    item: CriterionOutcome,
) -> Verified:
    """One criterion. An attestation keeps its outcome unless the model contradicts it."""
    criterion: EligibilityCriterion = item.criterion
    attestation = criterion.kind == CriterionKind.APPLICANT_ATTEST

    def failed(reason: str) -> CriterionOutcome:
        # A failure never changes an attestation: it was outstanding before, and
        # nothing was learnt. A narrative condition stays undecided, with the reason.
        return item if attestation else _undecided(item, reason)

    retrieval = retrieve(call, criterion)
    if not retrieval.complete or not retrieval.passages:
        return Verified(failed(INCOMPLETE))
    passages = retrieval.passages

    try:
        result = gateway.run(
            TASK,
            variables={
                "criterion": criterion.label_mk,
                "criterion_quote": criterion.source_quote or "",
                "applicant": applicant_shape(profile),
                "passages": render_passages(passages),
            },
            response_model=VerificationResult,
            on_invalid=ReviewKind.VERIFICATION,
            call_id=call.id,
        )
    except InvalidModelOutput as exc:
        return Verified(failed(INVALID), review_item_id=exc.review_item_id)
    answer: VerificationResult = result.output

    evidence = None
    if answer.passage is not None:
        if answer.passage > len(passages) or answer.quote not in passages[answer.passage - 1].text:
            why = (
                f"passage {answer.passage} of {len(passages)} does not exist"
                if answer.passage > len(passages)
                else f"the quote is not in passage {answer.passage}"
            )
            review_id = _review(session_factory, call, criterion, result, passages, why)
            return Verified(failed(UNVERIFIABLE), review_item_id=review_id)
        passage = passages[answer.passage - 1]
        start = passage.char_start + passage.text.index(answer.quote)
        evidence = Evidence(
            snapshot_id=passage.snapshot_id,
            char_start=start,
            char_end=start + len(answer.quote),
            quote=answer.quote,
            confidence=answer.confidence,
            verdict=answer.verdict,
            reasoning_mk=answer.reasoning_mk,
            model_call_id=result.model_call_id,
        )

    if attestation:
        if answer.verdict == "not_satisfied" and answer.confidence >= MIN_CONFIDENCE:
            return Verified(_undecided(item, answer.reasoning_mk), evidence)
        return Verified(item, evidence)
    if answer.confidence < MIN_CONFIDENCE:
        return Verified(_undecided(item, answer.reasoning_mk), evidence)
    return Verified(_decided(item, answer.verdict, answer.reasoning_mk), evidence)


# ------------------------------------------------------------------ one call


def verify_call(
    gateway: Gateway,
    session_factory,
    retrieve: Retriever,
    profile: Profile,
    outcome: CallOutcome,
) -> tuple[CallOutcome, list[Verified]]:
    """Verify one call's narrative criteria and attestations, and settle it again.

    A call the rules already exclude is left alone: nothing a model says can
    change `not_eligible`, and the tokens would buy nothing.
    """
    if outcome.verdict == Verdict.NOT_ELIGIBLE:
        return outcome, []
    items, verified = [], []
    for item in outcome.outcomes:
        narrative = (
            item.criterion.kind == CriterionKind.NARRATIVE_VERIFY
            and item.decision.outcome == Outcome.UNCLEAR
        )
        if narrative or item.criterion.kind == CriterionKind.APPLICANT_ATTEST:
            v = verify_criterion(gateway, session_factory, retrieve, profile, outcome.call, item)
            verified.append(v)
            item = v.outcome
        items.append(item)
    return stage1.settle(outcome.call, items, outcome.preferences), verified
