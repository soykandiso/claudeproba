"""The free shortlist: stages 1 and 2 for one profile, and every citation re-checked.

This is what `/povici` shows (roadmap P2 s28). Three things happen here that no
earlier stage does:

**Every quote is found again before it is shown.** An approved criterion's quote
was checked when a reviewer approved it, and the check constraint guarantees it has
offsets — but a citation shown to a customer is a claim, and CLAUDE.md invariant 2
says it is checked in code, not trusted. One query compares each cited span of the
stored snapshot with the quote. A criterion whose quote is not there any more is
treated as undecided, and the call's verdict is settled again from that: a broken
citation can move a call to `needs_verification`, never anywhere else (invariant 3).
That includes `not_eligible` — an exclusion nobody can show the words for is not
shown as one.

**The free depth is the top ten** (docs/decisions.md D6), with reasons and
citations, and the page says how many open calls there were in all. Calls the
rules exclude are listed apart, never dropped.

**Rank-before-judging is not done**, although the roadmap row names it. Measured
22.09.2026 (`ops/dev/bench_stage1.py`, `matching.md` §3): stage 1 over 2.000 open
calls is 274 ms, and the country will not publish that many open calls at once for
years. Judging only the best-ranked calls would need batching to keep ten open
ones on the page and would hide excluded calls further down — a moving part bought
for a registry ten times the size of the real one. Re-run the bench when the open
registry passes 2.000.
"""

import datetime as dt
import uuid
from dataclasses import dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.matching import stage1, stage2
from app.matching.normalise import Profile
from app.matching.stage1 import CallOutcome, CriterionOutcome
from app.matching.taxonomy import Decision, Outcome, criterion_verdict
from app.models import Call, EligibilityCriterion, Programme, RawSnapshot

# docs/decisions.md D6: the free shortlist shows the full top ten with reasons.
FREE_DEPTH = 10

BROKEN_CITATION = (
    "Цитатот повеќе не се наоѓа во зачуваниот текст на повикот, па условот се проверува повторно."
)


@dataclass(frozen=True)
class Citation:
    """What a customer is shown beside a condition: the words, and where they are."""

    criterion_id: uuid.UUID
    snapshot_id: int
    char_start: int
    char_end: int
    quote: str
    source_url: str
    retrieved_at: dt.datetime


@dataclass(frozen=True)
class Entry:
    scored: stage2.Scored
    citations: dict[uuid.UUID, Citation]
    institution: str

    @property
    def call(self) -> Call:
        return self.scored.call

    @property
    def outcome(self) -> CallOutcome:
        return self.scored.outcome

    def citation(self, item: CriterionOutcome) -> Citation | None:
        return self.citations.get(item.criterion.id)


@dataclass(frozen=True)
class Shortlist:
    open: list[Entry]
    open_total: int
    excluded: list[Entry]
    excluded_total: int
    weights_version: str


def _verified(session: Session, criteria: list[EligibilityCriterion]) -> dict:
    """Citation per criterion whose quote is still at its offsets, in one query."""
    if not criteria:
        return {}
    length = EligibilityCriterion.quote_end - EligibilityCriterion.quote_start
    rows = session.execute(
        select(
            EligibilityCriterion.id,
            RawSnapshot.id,
            EligibilityCriterion.quote_start,
            EligibilityCriterion.quote_end,
            EligibilityCriterion.source_quote,
            func.coalesce(EligibilityCriterion.source_url, RawSnapshot.url),
            RawSnapshot.fetched_at,
        )
        .join(RawSnapshot, RawSnapshot.id == EligibilityCriterion.snapshot_id)
        .where(
            EligibilityCriterion.id.in_([c.id for c in criteria]),
            # Offsets are characters in Python and in PostgreSQL's substr alike.
            func.substr(RawSnapshot.normalised_text, EligibilityCriterion.quote_start + 1, length)
            == EligibilityCriterion.source_quote,
        )
    )
    return {row[0]: Citation(*row) for row in rows}


def _recheck(outcome: CallOutcome, citations: dict) -> CallOutcome:
    """Treat a criterion whose words cannot be shown as undecided, and settle again."""
    if all(o.criterion.id in citations for o in outcome.outcomes):
        return outcome
    items = []
    for o in outcome.outcomes:
        if o.criterion.id not in citations:
            unclear = Decision(Outcome.UNCLEAR, o.decision.decided_by)
            o = replace(
                o, decision=unclear, verdict=criterion_verdict(unclear), reason_mk=BROKEN_CITATION
            )
        items.append(o)
    return stage1.settle(outcome.call, items, outcome.preferences)


def build(session: Session, profile: Profile, now: dt.datetime | None = None) -> Shortlist:
    now = now or dt.datetime.now(dt.UTC)
    outcomes = stage1.run(session, profile, now)
    criteria = [o.criterion for outcome in outcomes for o in outcome.outcomes]
    citations = _verified(session, criteria)
    outcomes = [_recheck(outcome, citations) for outcome in outcomes]

    ranked = stage2.rank(outcomes, profile, now)
    institutions = dict(
        session.execute(
            select(Call.id, Programme.institution)
            .join(Programme, Programme.id == Call.programme_id)
            .where(Call.id.in_([s.call.id for s in ranked]))
        ).all()
    )
    entries = [Entry(s, citations, institutions.get(s.call.id, "")) for s in ranked]
    open_ = [e for e in entries if not e.scored.excluded]
    excluded = [e for e in entries if e.scored.excluded]
    return Shortlist(
        open=open_[:FREE_DEPTH],
        open_total=len(open_),
        excluded=excluded[:FREE_DEPTH],
        excluded_total=len(excluded),
        weights_version=stage2.WEIGHTS_VERSION,
    )
