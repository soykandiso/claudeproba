"""Stage 1 over the registry: which calls are worth judging, and what the rules say.

Two steps, deliberately separate (docs/matching.md §3).

**1a is SQL on indexed columns only** — `candidates()`. It exists to make the work
small, not to decide anything. Every predicate it adds can only be a *superset*
filter: if it throws a call away, the interpreter would certainly have called that
call `not_eligible` anyway. Two consequences run through the whole module:

- **A predicate the profile cannot answer is not applied at all.** No activity in
  the profile means no NACE clause, not an empty overlap. Filtering on a blank is
  how "we do not know" silently becomes "you may not apply" (CLAUDE.md invariant 3).
- **A banded profile is compared permissively.** `min/max_company_age_months` are
  exact months and `Profile.age_months` is a range, so a call is kept when *any*
  month in the applicant's range could satisfy it. The interpreter then judges the
  same range conservatively and answers *unclear* where it straddles, which asks.

**1b is the interpreter in Python** — `judge()`. It reads every approved criterion
of a surviving call: `hard_structured` goes to `app/matching/hard_filter.py`, the
only code permitted to exclude anyone; `applicant_attest` and `documentary` are
outstanding until the company confirms or brings them; `narrative_verify` is not
decided here at all — `app/matching/verify.py` reads it against the call's text
(stage 3, paid) — and an undecided criterion is *unclear*, which is why the free
shortlist says `needs_verification` for most calls. That is the honest state of
what a rule can know, not a placeholder to be optimised away.

**The eligibility gap.** A call whose own documents are known not to hold all of
its conditions (`call.eligibility_gap`, set for EU topics whose conditions point at
an unfetched call document — `docs/sources.md` §6.6) can never be shown as
`eligible` or `likely_eligible`, however many criteria it satisfies. An unread
document can only add conditions, never remove one, so `not_eligible` still stands.
"""

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, cast, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.types import Text

from app.matching import intake
from app.matching.hard_filter import RuleResult, Stored, evaluate
from app.matching.normalise import Profile
from app.matching.operators import ProfileField
from app.matching.taxonomy import DecidedBy, Decision, Outcome, call_verdict, criterion_verdict
from app.models import Call, EligibilityCriterion
from app.models.enums import CallStatus, CriterionKind, Verdict

# ------------------------------------------------------------------ stage 1a


def _empty(column: ColumnElement) -> ColumnElement:
    """True when a denormalised array says "no restriction" (docs/matching.md §3)."""
    return func.coalesce(func.cardinality(column), 0) == 0


def candidate_query(profile: Profile, now: dt.datetime) -> Select:
    """The SQL of stage 1a: published, open, still in time, and not obviously excluded.

    Every clause below is guarded by whether the profile answers it, because an
    unanswered question must not narrow the registry.
    """
    where = [
        Call.is_published.is_(True),
        Call.status == CallStatus.OPEN,
        or_(Call.deadline_at.is_(None), Call.deadline_at > now),
    ]

    if profile.entity_types:
        where.append(
            or_(
                _empty(Call.allowed_entity_types),
                # The right side is cast, never the column: casting the column
                # would put an expression where the index expects a value.
                Call.allowed_entity_types.overlap(
                    cast(sorted(profile.entity_types), Call.allowed_entity_types.type)
                ),
            )
        )
    if profile.nace_prefixes:
        where.append(
            or_(
                _empty(Call.allowed_nace_prefixes),
                Call.allowed_nace_prefixes.overlap(cast(list(profile.nace_prefixes), ARRAY(Text))),
            )
        )
    # `allowed_regions` is always empty today — geography is not in the rule
    # vocabulary yet (app/matching/operators.py) — but the clause is written so
    # that filling the column is the only change needed. A municipality and its
    # region are both offered, because a call names one or the other.
    places = [p for p in (profile.region_code, profile.municipality_code) if p]
    if places:
        where.append(
            or_(
                _empty(Call.allowed_regions),
                Call.allowed_regions.overlap(cast(places, ARRAY(Text))),
            )
        )
    if profile.age_months is not None:
        # Permissive on purpose: keep the call if any month in the range could pass.
        where.append(
            or_(
                Call.min_company_age_months.is_(None),
                Call.min_company_age_months <= profile.age_months.hi,
            )
        )
        where.append(
            or_(
                Call.max_company_age_months.is_(None),
                Call.max_company_age_months >= profile.age_months.lo,
            )
        )

    return select(Call).where(*where).order_by(Call.deadline_at.asc().nullslast(), Call.title_mk)


def candidates(session: Session, profile: Profile, now: dt.datetime | None = None) -> list[Call]:
    return list(session.scalars(candidate_query(profile, now or _now())))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# ------------------------------------------------------------------ stage 1b


@dataclass(frozen=True)
class CriterionOutcome:
    criterion: EligibilityCriterion
    decision: Decision
    verdict: Verdict
    reason_mk: str


@dataclass(frozen=True)
class CallOutcome:
    call: Call
    verdict: Verdict
    outcomes: list[CriterionOutcome]
    # Why `eligible` was withheld although the criteria allowed it, or None.
    capped_by: str | None = None
    # Approved `soft_scored` criteria: extra points in stage 2, never judged here.
    preferences: tuple[EligibilityCriterion, ...] = ()

    @property
    def open_items(self) -> list[CriterionOutcome]:
        return [o for o in self.outcomes if o.verdict != Verdict.ELIGIBLE]


FIELD_NOTE = {
    ProfileField.ENTITY_TYPE: lambda p: intake.entity_label(p) or "",
    ProfileField.NACE_CODE: lambda p: f"дејност {p.nace_code}" if p.nace_code else "",
    ProfileField.AGE_MONTHS: lambda p: (
        f"основана {p.answers.get('founded')}" if p.age_months else ""
    ),
    ProfileField.HEADCOUNT: lambda p: (
        f"{intake.employees_label(p)} вработени" if intake.employees_label(p) else ""
    ),
    ProfileField.INVESTMENT_SIZE_MKD: lambda p: intake.amount_label(p) or "",
}

MISSING = "Профилот не го содржи податокот што го бара овој услов."
STRADDLES = "Одговорот во профилот е опсег што не е доволен за да се одлучи."
PENDING = "Ќе се провери според текстот на повикот."
ATTEST = "Го потврдувате вие при пријавата."
DOCUMENT = "Документот го доставувате вие со пријавата."


def _rule_reason(profile: Profile, field: ProfileField, result: RuleResult) -> str:
    shown = FIELD_NOTE.get(field, lambda _: "")(profile)
    if not shown:
        return MISSING
    if result == RuleResult.UNCLEAR:
        return f"Во профилот: {shown}. {STRADDLES}"
    return f"Во профилот: {shown}."


def _decide(criterion: EligibilityCriterion, profile: Profile) -> tuple[Decision, str]:
    if criterion.kind == CriterionKind.HARD_STRUCTURED:
        try:
            stored = Stored.from_row(criterion.field, criterion.operator, criterion.value_json)
        except ValueError:
            # A stored row naming a field or operator the vocabulary no longer has —
            # possible only if `app/matching/operators.py` narrows under rows already
            # approved. Ask, never exclude, and never raise inside a web request.
            return Decision(Outcome.UNCLEAR, DecidedBy.RULE), MISSING
        result = evaluate(stored, profile.rules_view)
        return Decision(Outcome(result.value), DecidedBy.RULE), _rule_reason(
            profile, stored.field, result
        )
    if criterion.kind == CriterionKind.APPLICANT_ATTEST:
        return Decision(Outcome.ATTEST, DecidedBy.APPLICANT), ATTEST
    if criterion.kind == CriterionKind.DOCUMENTARY:
        # A document the application must include is the applicant's to bring,
        # like a declaration: outstanding, never settled by us, so the call can
        # reach likely_eligible and never eligible. Decided in P2 s29, when the
        # verification pass arrived and this was the kind it could not read.
        return Decision(Outcome.ATTEST, DecidedBy.APPLICANT), DOCUMENT
    return Decision(Outcome.UNCLEAR, DecidedBy.MODEL), PENDING


def judge(call: Call, criteria: Iterable[EligibilityCriterion], profile: Profile) -> CallOutcome:
    """One call against one profile. Only approved criteria are ever read.

    An unapproved criterion is a model's unreviewed opinion; letting one decide
    anything would put the model back in the eligibility path (invariant 1).
    """
    outcomes, preferences = [], []
    for criterion in criteria:
        if not criterion.is_approved:
            continue
        if criterion.kind == CriterionKind.SOFT_SCORED:
            # A preference raises a call's rank and excludes no one, so it has no
            # say in the verdict: judged, it would come out *unclear* and pull an
            # otherwise decided call down to needs_verification.
            preferences.append(criterion)
            continue
        decision, reason = _decide(criterion, profile)
        outcomes.append(CriterionOutcome(criterion, decision, criterion_verdict(decision), reason))

    return settle(call, outcomes, preferences)


def settle(call: Call, outcomes: list[CriterionOutcome], preferences: Iterable = ()) -> CallOutcome:
    """The call's verdict from its criteria's, with the eligibility gap applied.

    Separate from `judge` so a later step that downgrades one criterion — the
    shortlist's citation check — reaches the verdict by the same road.
    """
    verdict = call_verdict(o.decision for o in outcomes)
    capped = None
    if call.eligibility_gap and verdict in (Verdict.ELIGIBLE, Verdict.LIKELY_ELIGIBLE):
        verdict, capped = Verdict.NEEDS_VERIFICATION, call.eligibility_gap
    return CallOutcome(call, verdict, outcomes, capped, tuple(preferences))


# ------------------------------------------------------------------ both steps


def _criteria_by_call(session: Session, calls: Sequence[Call]) -> dict:
    if not calls:
        return {}
    rows = session.scalars(
        select(EligibilityCriterion)
        .where(
            EligibilityCriterion.call_id.in_([c.id for c in calls]),
            EligibilityCriterion.is_approved.is_(True),
        )
        .order_by(EligibilityCriterion.call_id, EligibilityCriterion.extracted_at)
    )
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row.call_id, []).append(row)
    return grouped


def run(session: Session, profile: Profile, now: dt.datetime | None = None) -> list[CallOutcome]:
    """Stage 1 end to end: the open registry narrowed, then judged.

    Order is by deadline, which is stage 1a's; ranking is `stage2.rank` and
    deliberately not done here. Calls the rules exclude are returned too — the
    shortlist page shows them separately, with the reason, rather than dropping
    them silently (docs/matching.md §3).
    """
    found = candidates(session, profile, now)
    criteria = _criteria_by_call(session, found)
    return [judge(call, criteria.get(call.id, []), profile) for call in found]
