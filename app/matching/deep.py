"""Stage 3 on the worker: the paid report's top five calls, verified and stored (P2 s31).

docs/architecture.md §6. The order flow (P4) enqueues one job per paid report with
the `applicant_profile` it was bought for; the job runs on the `analysis` queue,
where the embedder can be loaded (the web process cannot hold the model). What it
does, in order:

1. **Stage 0 again, over the stored answers** (`normalise.from_row`). The row holds
   the answers exactly as the form posted them, so the profile the report is
   computed from is the one the customer described, re-read by the same function.
2. **Stages 1–2, as the free shortlist does them** (`shortlist.ranked`): the same
   candidates, the same citation re-check, the same order. A report that verified
   a different five than the page the customer paid from would be a different
   product.
3. **The `match_run` row is written and committed** before any model is asked, so
   every model call and review item the run causes points at it — that is what
   s36's cost per report is summed from.
4. **Stage 3 over the top five open calls** (`verify.verify_call`). A call the
   rules exclude is never among them: nothing a model says can change it.
5. **Every model citation is found again in the stored text** before it is kept
   (invariant 2). A chunk is a span of the snapshot by construction, so this should
   never fail; if it does, the condition is undecided and a person is asked,
   exactly as for a quote not in its passage.
6. **Results, per-criterion outcomes and evidence are written in one commit**, and
   the run is marked `stage_reached = 3`. A run still at 2 is one whose job did not
   finish; running the job again makes a new run, and the gateway's content-hash
   cache means the answers already paid for are not paid for twice.

Only the five verified calls get result rows; `candidates_considered` says how many
stages 1–2 ranked. The calls the rules exclude are the free shortlist's to list.

**A provider failure fails the job.** An exception from the gateway (the provider
down, a prompt file changed under a route) propagates: RQ keeps the failed job, and
no half-verified report is stored as if it were finished. An answer that is merely
wrong is not a failure — the gates in `verify.py` turn it into *needs verification*.
"""

import datetime as dt
import time
import uuid
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import Routing
from app.matching import normalise, reference, shortlist, stage1, stage2, verify
from app.matching.stage1 import CallOutcome
from app.matching.taxonomy import DecidedBy, Decision, Outcome, criterion_verdict
from app.models import (
    ApplicantProfile,
    Evidence,
    MatchCriterionOutcome,
    MatchResult,
    MatchRun,
    RawSnapshot,
    ReviewQueueItem,
)
from app.models.enums import ReviewKind

QUEUE = "analysis"

# docs/matching.md §5: the verification pass reads the top five calls only.
DEPTH = 5

# Five calls of a dozen conditions each, one model call per condition, plus the
# embedder's first load: minutes, not seconds. Generous, so a slow provider fails
# as a provider error rather than as a timeout halfway through a call.
JOB_TIMEOUT_S = 30 * 60

VERIFIED_STAGE = 3


def ruleset_version() -> str:
    """What besides the approved criteria decided a run: reference data and the prompt."""
    prompt = Routing.load().route(verify.TASK).prompt_version
    return f"ref {reference.version()}; {verify.TASK} {prompt}"


@dataclass(frozen=True)
class Report:
    """What one run stored, for the caller and the tests."""

    match_run_id: uuid.UUID
    ranked: list[stage2.Scored]
    verified: dict[uuid.UUID, list[verify.Verified]]


# ------------------------------------------------------------------ the evidence check


def _located(session: Session, evidence: list[verify.Evidence]) -> set[tuple]:
    """The (snapshot, start, end, quote) of every evidence found at its offsets."""
    if not evidence:
        return set()
    texts = dict(
        session.execute(
            select(RawSnapshot.id, RawSnapshot.normalised_text).where(
                RawSnapshot.id.in_({e.snapshot_id for e in evidence})
            )
        ).all()
    )
    return {
        _key(e)
        for e in evidence
        if (texts.get(e.snapshot_id) or "")[e.char_start : e.char_end] == e.quote
    }


def _key(e: verify.Evidence) -> tuple:
    return e.snapshot_id, e.char_start, e.char_end, e.quote


def _recheck(
    session: Session,
    outcome: CallOutcome,
    verified: list[verify.Verified],
    match_run_id: uuid.UUID,
) -> tuple[CallOutcome, list[verify.Verified]]:
    """Drop evidence that is not where it says, and make its condition undecided."""
    found = _located(session, [v.evidence for v in verified if v.evidence])
    lost = {
        v.outcome.criterion.id: v for v in verified if v.evidence and _key(v.evidence) not in found
    }
    if not lost:
        return outcome, verified
    for v in lost.values():
        session.add(
            ReviewQueueItem(
                kind=ReviewKind.VERIFICATION,
                reason=f"{verify.TASK}: the quote is not at its offsets in the stored text",
                call_id=outcome.call.id,
                match_run_id=match_run_id,
                payload={
                    "stage": "deep",
                    "criterion_id": str(v.outcome.criterion.id),
                    "criterion": v.outcome.criterion.label_mk,
                    "model_call_id": v.evidence.model_call_id,
                    "snapshot_id": v.evidence.snapshot_id,
                    "char_start": v.evidence.char_start,
                    "quote": v.evidence.quote,
                },
            )
        )
    # Undecided is a downgrade whatever the condition was, so it is safe for an
    # attestation too (invariant 3): the words that would have decided it are gone.
    unclear = Decision(Outcome.UNCLEAR, DecidedBy.MODEL)
    items = [
        replace(
            o, decision=unclear, verdict=criterion_verdict(unclear), reason_mk=verify.UNVERIFIABLE
        )
        if o.criterion.id in lost
        else o
        for o in outcome.outcomes
    ]
    verified = [
        replace(v, evidence=None) if v.outcome.criterion.id in lost else v for v in verified
    ]
    return stage1.settle(outcome.call, items, outcome.preferences), verified


# ------------------------------------------------------------------ writing it down


def _write(
    session: Session,
    run: MatchRun,
    ranked: list[stage2.Scored],
    verified: dict[uuid.UUID, list[verify.Verified]],
) -> None:
    evidence = [v.evidence for vs in verified.values() for v in vs if v.evidence]
    urls = dict(
        session.execute(
            select(RawSnapshot.id, RawSnapshot.url).where(
                RawSnapshot.id.in_({e.snapshot_id for e in evidence})
            )
        ).all()
    )
    for rank, scored in enumerate(ranked, 1):
        result = MatchResult(
            match_run_id=run.id,
            call_id=scored.call.id,
            verdict=scored.outcome.verdict,
            score=round(scored.score, 4),
            score_breakdown={
                p.name: {"value": p.value, "weight": p.weight, "reason": p.reason_mk}
                for p in scored.parts
            },
            rank=rank,
        )
        session.add(result)
        session.flush()
        by_criterion = {v.outcome.criterion.id: v for v in verified.get(scored.call.id, [])}
        for item in scored.outcome.outcomes:
            found = by_criterion.get(item.criterion.id)
            model = found.evidence if found else None
            row = MatchCriterionOutcome(
                match_result_id=result.id,
                criterion_id=item.criterion.id,
                verdict=item.verdict,
                confidence=model.confidence if model else None,
                decided_by=item.decision.decided_by.value,
                reason_mk=item.reason_mk,
            )
            session.add(row)
            if model is None:
                continue
            session.flush()
            session.add(
                Evidence(
                    outcome_id=row.id,
                    snapshot_id=model.snapshot_id,
                    quote=model.quote,
                    char_start=model.char_start,
                    char_end=model.char_end,
                    source_url=urls[model.snapshot_id],
                )
            )


# ------------------------------------------------------------------ the run


def run(
    session_factory,
    gateway,
    retriever_for,
    profile_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> Report:
    """Verify one profile's top five calls and store the report's inputs.

    `retriever_for(session)` builds the retriever over the run's own session:
    `verify.call_retriever` with the worker's embedder in production, a fixture
    retriever in the evaluation and the tests.
    """
    now = now or dt.datetime.now(dt.UTC)
    started = time.monotonic()
    with session_factory() as session:
        row = session.get(ApplicantProfile, profile_id)
        if row is None:
            raise LookupError(f"no applicant_profile {profile_id}")
        profile = normalise.from_row(row, now.date())
        scored, _ = shortlist.ranked(session, profile, now)
        top = [s for s in scored if not s.excluded][:DEPTH]

        match_run = MatchRun(
            profile_id=row.id,
            ruleset_version=ruleset_version(),
            weights_version=stage2.WEIGHTS_VERSION,
            stage_reached=2,
            candidates_considered=len(scored),
        )
        session.add(match_run)
        session.commit()

        retrieve = retriever_for(session)
        outcomes, verified = [], {}
        for s in top:
            outcome, results = verify.verify_call(
                gateway, session_factory, retrieve, profile, s.outcome, match_run.id
            )
            outcome, results = _recheck(session, outcome, results, match_run.id)
            outcomes.append(outcome)
            verified[outcome.call.id] = results
        ranked = stage2.rank(outcomes, profile, now)

        _write(session, match_run, ranked, verified)
        match_run.stage_reached = VERIFIED_STAGE
        match_run.duration_ms = int((time.monotonic() - started) * 1000)
        session.commit()
        return Report(match_run.id, ranked, verified)


# ------------------------------------------------------------------ the worker


def job(profile_id: str) -> dict:
    """What the RQ worker runs. Builds its own settings, connections and embedder."""
    from app.ai.gateway import AnthropicProvider, Gateway
    from app.config import load_settings
    from app.db import session_factory
    from app.retrieval.embedder import LocalEmbedder

    settings = load_settings()
    sessions = session_factory(settings)
    embedder = LocalEmbedder(settings.model_dir)
    report = run(
        sessions,
        Gateway(sessions, AnthropicProvider()),
        lambda session: verify.call_retriever(session, embedder),
        uuid.UUID(str(profile_id)),
    )
    return {"match_run_id": str(report.match_run_id), "calls": len(report.ranked)}


def enqueue(settings, profile_id: uuid.UUID) -> str:
    """Hand a paid report to the worker. Raises when Redis cannot be reached."""
    from redis import Redis
    from rq import Queue

    queue = Queue(QUEUE, connection=Redis.from_url(settings.redis_url, socket_timeout=5))
    queued = queue.enqueue(
        job,
        str(profile_id),
        job_timeout=JOB_TIMEOUT_S,
        description=f"deep analysis {profile_id}",
    )
    return queued.id
