"""Tier A of the evaluation harness: stages 0–2 over frozen calls. No network, no model.

Run it with `evals/run.py`; this module is the machinery, and `docs/matching.md` §8
is the design it implements.

**What tier A is.** Ten applicant profiles (`evals/profiles/`) against five real
calls frozen with their documents and their approved criteria (`evals/fixtures/`,
rebuilt by `ops/dev/freeze_eval_fixtures.py`). The registry is loaded into
PostgreSQL inside a transaction that is rolled back, because stage 1a *is* SQL and
a harness that skipped it would measure a different program than the one that
answers customers.

**Two kinds of finding, and only one of them needs the user's evening.**

*Properties* hold for every profile and every call, with no expected answers at
all, and all four are checked on every run from today:

1. every criterion's quote is verbatim in the document it cites, at the offsets it
   cites (CLAUDE.md invariant 2 — "checked in code, not trusted");
2. stage 1a is a superset filter: a call the SQL threw away must be one the
   interpreter would have called `not_eligible` anyway. This is the one place
   where a wrong answer is invisible in the product — a call that never appears
   has no reason next to it;
3. only a rule excluded anyone (invariant 1);
4. no call carrying an `eligibility_gap` rose above `needs_verification`, however
   well its extracted criteria went (invariant 3, `docs/sources.md` §6.6).

*Cases* are the expected verdicts in `evals/cases/`, one line of judgement per
(profile × call) from someone who knows the subject — roadmap P2 s26. They are
what the accuracy thresholds are measured against, and there are none yet, which
is why the gate is red: **an empty suite proves nothing.** That red is the roadmap
row, not a bug.

**Why the gate is asymmetric.** A false `eligible` costs a customer money on an
application they could never win; a false `not_eligible` costs one missed
opportunity. The thresholds in `evals/suite.yaml` treat them accordingly, and
"the system is less certain than the truth" is not a failure at all — it is the
distance s27 (scoring) and s29 (verification) have to close, so it is reported as
a number rather than gated.
"""

import datetime as dt
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.matching import stage1, stage2
from app.matching.hard_filter import Stored, prefilter_columns
from app.matching.normalise import Profile, normalise
from app.matching.taxonomy import DecidedBy
from app.models import Call, EligibilityCriterion, Programme, RawSnapshot, SourceFeed
from app.models.enums import AccessMethod, CallStatus, CriterionKind, TextSource, Verdict

ROOT = Path(__file__).resolve().parent
PROFILES = ROOT / "profiles"
FIXTURES = ROOT / "fixtures"
CASES = ROOT / "cases"
SUITE = ROOT / "suite.yaml"

# A call that stage 1a never returned. Not a verdict: the shortlist simply does not
# contain it, which is a different thing to say to a customer than "not eligible",
# and the two are worth telling apart in a case file.
NOT_SHOWN = "not_shown"
EXPECTED = {str(v) for v in Verdict} | {NOT_SHOWN}
EXCLUDES = {str(Verdict.NOT_ELIGIBLE), NOT_SHOWN}
CLAIMS_ELIGIBLE = {str(Verdict.ELIGIBLE), str(Verdict.LIKELY_ELIGIBLE)}


# ------------------------------------------------------------------ what is loaded


@dataclass(frozen=True)
class ProfileCase:
    """One applicant fixture: the answers a form would post, and why it exists."""

    key: str
    name: str
    boundary: str
    answers: dict

    def profile(self, as_of: dt.date) -> Profile:
        return normalise(self.answers, today=as_of)


@dataclass(frozen=True)
class Fixture:
    """One frozen call: its columns, its approved criteria, and the document text."""

    slug: str
    data: dict
    text: str

    @property
    def title(self) -> str:
        return self.data["title_mk"]

    @property
    def criteria(self) -> list[dict]:
        return self.data["criteria"]

    @property
    def shortlistable(self) -> bool:
        """An advance notice is in the registry but cannot be applied to."""
        return self.data["status"] == str(CallStatus.OPEN)


@dataclass(frozen=True)
class Case:
    """One expected verdict, written by a person who knows the answer (s26)."""

    profile: str
    call: str
    expected: str
    reason: str


@dataclass
class Observed:
    verdict: str  # a Verdict, or NOT_SHOWN
    capped_by: str | None = None
    open_items: int = 0


def load_suite() -> dict:
    return yaml.safe_load(SUITE.read_text(encoding="utf-8"))


def load_profiles() -> dict[str, ProfileCase]:
    found = {}
    for path in sorted(PROFILES.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        found[path.stem] = ProfileCase(
            key=path.stem,
            name=data["name"],
            boundary=data.get("boundary", "").strip(),
            answers=data["answers"],
        )
    return found


def load_fixtures() -> dict[str, Fixture]:
    found = {}
    for directory in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        data = yaml.safe_load((directory / "call.yaml").read_text(encoding="utf-8"))
        text = (directory / data["document"]["path"]).read_text(encoding="utf-8")
        found[directory.name] = Fixture(directory.name, data, text)
    return found


def load_cases(profiles: dict, fixtures: dict) -> tuple[list[Case], list[str], int]:
    """Every answered row in `evals/cases/`, the complaints, and how many are blank.

    A blank `expect` is not an error: the worksheet is filled in over an evening
    and a half-finished file has to keep working. A row naming something that does
    not exist is an error, because it is silently measuring nothing.
    """
    cases, problems, unanswered = [], [], 0
    for path in sorted(CASES.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        where = f"cases/{path.relative_to(CASES)}"
        call = data.get("call")
        if call not in fixtures:
            problems.append(f"{where}: no frozen call named {call!r}")
            continue
        for row in data.get("cases") or []:
            expected = (row.get("expect") or "").strip()
            if not expected:
                unanswered += 1
                continue
            if row.get("profile") not in profiles:
                problems.append(f"{where}: no profile named {row.get('profile')!r}")
                continue
            if expected not in EXPECTED:
                problems.append(f"{where}: {row['profile']}: {expected!r} is not a verdict")
                continue
            reason = (row.get("reason") or "").strip()
            if not reason:
                problems.append(f"{where}: {row['profile']}: an expected verdict needs a reason")
                continue
            cases.append(Case(row["profile"], call, expected, reason))
    return cases, problems, unanswered


# --------------------------------------------------------- the registry, frozen


def load_registry(session: Session, fixtures: dict[str, Fixture]) -> dict[str, Call]:
    """Write the frozen calls into the database as approved, published rows.

    Everything a real call carries is written the way the real path writes it: the
    document becomes a snapshot with its normalised text, the criteria cite offsets
    into that text, and the denormalised prefilter columns are computed by
    `hard_filter.prefilter_columns` — the same function `app/review/extraction.py`
    calls when a human approves a call. Hand-writing those columns instead would
    hide the one seam stage 1a depends on.

    Calls already published in this database are removed first: stage 1 selects
    across the whole registry, so anything left over joins every candidate set
    (the same reason `tests/test_stage1.py` does it). The caller runs this inside a
    transaction it rolls back.
    """
    session.execute(delete(Call).where(Call.is_published.is_(True)))
    calls = {}
    for slug, fixture in fixtures.items():
        data = fixture.data
        # Loading twice in one transaction is not an error — the calls are
        # replaced, and the feed and the snapshot are the same document either way.
        source = session.scalars(
            select(SourceFeed).where(SourceFeed.slug == f"eval-{slug}")
        ).first()
        if source is None:
            source = SourceFeed(
                slug=f"eval-{slug}",
                name_mk=data["institution"],
                name_en=data["institution"],
                institution=data["institution"],
                base_url=data["canonical_url"],
                access_method=AccessMethod.HTML,
                expected_cadence=dt.timedelta(days=1),
                staleness_sla=dt.timedelta(days=30),
            )
            session.add(source)
            session.flush()
        snapshot = session.scalars(
            select(RawSnapshot).where(
                RawSnapshot.url == data["canonical_url"],
                RawSnapshot.content_sha256 == data["document"]["sha256"],
            )
        ).first()
        if snapshot is None:
            snapshot = RawSnapshot(
                source_feed_id=source.id,
                url=data["canonical_url"],
                content_sha256=data["document"]["sha256"],
                http_status=200,
                storage_key=f"evals/{slug}",
                normalised_text=fixture.text,
                text_source=TextSource(data["document"]["text_source"]),
            )
            session.add(snapshot)
        programme = Programme(
            source_feed_id=source.id,
            slug=f"eval-{slug}-{uuid.uuid4()}",
            name_mk=data["title_mk"],
            institution=data["institution"],
            is_singleton=True,
        )
        session.add(programme)
        session.flush()

        stored = [
            Stored.from_row(c["field"], c["operator"], c["value_json"])
            for c in fixture.criteria
            if c["kind"] == str(CriterionKind.HARD_STRUCTURED)
        ]
        prefilter = prefilter_columns(stored)
        call = Call(
            programme_id=programme.id,
            source_feed_id=source.id,
            title_mk=data["title_mk"],
            reference_code=data["reference_code"],
            status=CallStatus(data["status"]),
            published_at=data["published_at"],
            deadline_at=data["deadline_at"],
            eligibility_gap=data["eligibility_gap"],
            grant_min_mkd=data.get("grant_min_mkd"),
            grant_max_mkd=data.get("grant_max_mkd"),
            cofinancing_pct=data.get("cofinancing_pct"),
            canonical_url=data["canonical_url"],
            primary_snapshot_id=snapshot.id,
            allowed_entity_types=prefilter.allowed_entity_types,
            allowed_nace_prefixes=prefilter.allowed_nace_prefixes,
            allowed_regions=prefilter.allowed_regions,
            min_company_age_months=prefilter.min_company_age_months,
            max_company_age_months=prefilter.max_company_age_months,
            is_published=True,
        )
        session.add(call)
        session.flush()
        for criterion in fixture.criteria:
            session.add(
                EligibilityCriterion(
                    call_id=call.id,
                    kind=CriterionKind(criterion["kind"]),
                    label_mk=criterion["label_mk"],
                    field=criterion["field"],
                    operator=criterion["operator"],
                    value_json=criterion["value_json"],
                    source_quote=criterion["quote"],
                    snapshot_id=snapshot.id,
                    quote_start=criterion["quote_start"],
                    quote_end=criterion["quote_end"],
                    source_url=data["canonical_url"],
                    confidence=criterion["confidence"],
                    is_approved=True,
                )
            )
        session.flush()
        calls[slug] = call
    return calls


# ------------------------------------------------------------------- the report


@dataclass
class Check:
    """One property that must hold however the suite is answered."""

    name: str
    checked: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


@dataclass
class Result:
    case: Case
    observed: Observed

    @property
    def matches(self) -> bool:
        return self.case.expected == self.observed.verdict

    @property
    def false_eligible(self) -> bool:
        return self.case.expected in EXCLUDES and self.observed.verdict in CLAIMS_ELIGIBLE

    @property
    def false_exclusion(self) -> bool:
        return self.case.expected in CLAIMS_ELIGIBLE and self.observed.verdict in EXCLUDES

    @property
    def under_decided(self) -> bool:
        """The system asks where the truth is known. Not a gate: s27 and s29 close it."""
        return self.case.expected != str(
            Verdict.NEEDS_VERIFICATION
        ) and self.observed.verdict == str(Verdict.NEEDS_VERIFICATION)

    @property
    def over_claimed(self) -> bool:
        return (
            self.case.expected == str(Verdict.NEEDS_VERIFICATION)
            and self.observed.verdict in CLAIMS_ELIGIBLE
        )


@dataclass
class Report:
    as_of: dt.date
    profiles: int
    fixtures: int
    checks: list[Check]
    results: list[Result]
    problems: list[str]
    unanswered: int
    latency_ms: list[float]
    gate: dict
    weights_version: str = stage2.WEIGHTS_VERSION
    open_calls: int = 0

    @property
    def median_latency_ms(self) -> float:
        if not self.latency_ms:
            return 0.0
        ordered = sorted(self.latency_ms)
        return ordered[len(ordered) // 2]

    def blocking(self) -> list[str]:
        """Everything that must be fixed before this code may be deployed."""
        blocked = [f"{c.name}: {len(c.failures)} failure(s)" for c in self.checks if not c.ok]
        blocked += [f"case files: {p}" for p in self.problems]
        if not self.results:
            blocked.append("no expected verdicts yet: an empty suite proves nothing (P2 s26)")
        false_eligible = [r for r in self.results if r.false_eligible]
        if len(false_eligible) > self.gate["false_eligible_max"]:
            blocked.append(f"false eligible: {len(false_eligible)} (zero tolerated)")
        if self.results:
            rate = len([r for r in self.results if r.false_exclusion]) / len(self.results)
            if rate > self.gate["false_exclusion_rate_max"]:
                blocked.append(
                    f"false exclusion: {rate:.1%} of cases "
                    f"(over {self.gate['false_exclusion_rate_max']:.0%})"
                )
        if self.median_latency_ms > self.gate["median_latency_block_ms"]:
            blocked.append(f"median stage 1–2 latency {self.median_latency_ms:.0f} ms")
        return blocked

    def warnings(self) -> list[str]:
        warned = []
        if self.unanswered:
            warned.append(f"{self.unanswered} case(s) still blank in evals/cases/")
        over = [r for r in self.results if r.over_claimed]
        if over:
            warned.append(f"{len(over)} case(s) claimed more than the expected verdict")
        if self.gate["median_latency_warn_ms"] < self.median_latency_ms:
            warned.append(f"median stage 1–2 latency {self.median_latency_ms:.0f} ms")
        return warned

    def text(self) -> str:
        lines = [
            f"tier A — {self.profiles} profiles × {self.fixtures} frozen calls, "
            f"as of {self.as_of:%d.%m.%Y}, weights {self.weights_version}",
            "",
            "properties",
        ]
        for check in self.checks:
            mark = "ok" if check.ok else "FAILED"
            lines.append(f"  {check.name:.<46} {check.checked:>4} checked  {mark}")
            lines += [f"      {failure}" for failure in check.failures]
        lines += [
            f"  {'median stage 1–2 latency':.<46} {self.median_latency_ms:>4.0f} ms",
            # Said, not scored: with this few open calls every ordering holds every
            # call in the top five, and a green "100%" would claim a measurement.
            f"  {'rank quality (top five)':.<46} not measurable: "
            f"{self.open_calls} open calls, no expected order in the cases",
            "",
            "cases",
        ]
        if not self.results:
            lines.append("  none answered yet — fill in evals/cases/ (roadmap P2 s26)")
        else:
            counts = Counter(
                (r.case.expected, r.observed.verdict) for r in self.results if not r.matches
            )
            exact = sum(1 for r in self.results if r.matches)
            lines.append(f"  {len(self.results)} answered, {exact} exactly as expected")
            for (expected, observed), count in sorted(counts.items()):
                lines.append(f"      expected {expected:<19} got {observed:<19} ×{count}")
            wrong = {
                "false eligible": [r for r in self.results if r.false_eligible],
                "false exclusion": [r for r in self.results if r.false_exclusion],
                "over-claimed": [r for r in self.results if r.over_claimed],
                "under-decided": [r for r in self.results if r.under_decided],
            }
            for name, rows in wrong.items():
                lines.append(f"  {name:.<46} {len(rows):>4}")
                # The two that block are named case by case, and so is over-claimed: it
                # does not block, but it is the nearest thing to a false eligible and a
                # count alone sends you looking for it. Under-decided will be most of the
                # suite until s27 and s29, and listing it would bury the rest.
                if name == "under-decided":
                    continue
                for row in rows[:10]:
                    lines.append(f"      {row.case.profile} × {row.case.call}: {row.case.reason}")
        for problem in self.problems:
            lines.append(f"  {problem}")
        lines.append("")
        blocked, warned = self.blocking(), self.warnings()
        for warning in warned:
            lines.append(f"warning: {warning}")
        if blocked:
            lines.append("GATE: FAILED")
            lines += [f"  - {reason}" for reason in blocked]
        else:
            lines.append("GATE: passed")
        return "\n".join(lines)


# -------------------------------------------------------------------- the run


def _citation_check(session: Session, calls: dict[str, Call]) -> Check:
    """Every quote verbatim at the offsets it cites. No citation, no claim."""
    check = Check("quotes verbatim in the cited document")
    for slug, call in calls.items():
        rows = session.scalars(
            select(EligibilityCriterion).where(EligibilityCriterion.call_id == call.id)
        )
        for row in rows:
            snapshot = session.get(RawSnapshot, row.snapshot_id)
            check.checked += 1
            found = (snapshot.normalised_text or "")[row.quote_start : row.quote_end]
            if found != row.source_quote:
                check.failures.append(
                    f"{slug}: {row.label_mk!r} cites {row.quote_start}–{row.quote_end}, "
                    f"which reads {found[:40]!r}"
                )
    return check


def _ranking_check(check: Check, key: str, by_id: dict, ranked: list[stage2.Scored]) -> None:
    """Every shortlisted call scored in [0, 1] with a reason per component, and no
    call the rules exclude above one the company may apply for."""
    seen_excluded = False
    for scored in ranked:
        check.checked += 1
        slug = by_id[scored.call.id]
        if not 0.0 <= scored.score <= 1.0:
            check.failures.append(f"{key} × {slug}: score {scored.score}")
        silent = [p.name for p in scored.parts if not p.reason_mk.strip()]
        if silent:
            check.failures.append(f"{key} × {slug}: no reason for {', '.join(silent)}")
        if seen_excluded and not scored.excluded:
            check.failures.append(f"{key} × {slug}: ranked below a call the rules exclude")
        seen_excluded = seen_excluded or scored.excluded


def run(session: Session, suite: dict | None = None) -> Report:
    """Load the frozen registry, run every profile through stages 1 and 2, and score it."""
    suite = suite or load_suite()
    as_of = suite["as_of"]
    now = dt.datetime.combine(as_of, dt.time(12, 0), tzinfo=dt.UTC)
    profiles, fixtures = load_profiles(), load_fixtures()
    cases, problems, unanswered = load_cases(profiles, fixtures)

    calls = load_registry(session, fixtures)
    by_id = {call.id: slug for slug, call in calls.items()}
    criteria = {
        slug: list(
            session.scalars(
                select(EligibilityCriterion)
                .where(EligibilityCriterion.call_id == call.id)
                .order_by(EligibilityCriterion.extracted_at)
            )
        )
        for slug, call in calls.items()
    }

    checks = [_citation_check(session, calls)]
    superset = Check("stage 1a filters only what the rules exclude")
    excluded_by = Check("only a rule may exclude an applicant")
    capped = Check("an unread document never allows eligible")
    ranked_check = Check("stage 2 gives a reason and ranks excluded last")
    latency: list[float] = []
    observed: dict[tuple[str, str], Observed] = {}

    for key, case_profile in profiles.items():
        profile = case_profile.profile(as_of)
        started = time.perf_counter()
        outcomes = stage1.run(session, profile, now)
        ranked = stage2.rank(outcomes, profile, now)
        latency.append((time.perf_counter() - started) * 1000)
        _ranking_check(ranked_check, key, by_id, ranked)

        shown = {by_id[o.call.id]: o for o in outcomes}
        for slug in fixtures:
            found = shown.get(slug)
            observed[(key, slug)] = (
                Observed(str(found.verdict), found.capped_by, len(found.open_items))
                if found
                else Observed(NOT_SHOWN)
            )
        for slug, outcome in shown.items():
            if outcome.call.eligibility_gap:
                capped.checked += 1
                if outcome.verdict in (Verdict.ELIGIBLE, Verdict.LIKELY_ELIGIBLE):
                    capped.failures.append(
                        f"{key} × {slug}: {outcome.verdict} although the call's own documents "
                        "are known not to hold all of its conditions"
                    )
            for item in outcome.outcomes:
                excluded_by.checked += 1
                excluded = item.verdict == Verdict.NOT_ELIGIBLE
                if excluded and item.decision.decided_by != DecidedBy.RULE:
                    excluded_by.failures.append(
                        f"{key} × {slug}: {item.criterion.label_mk!r} excluded by "
                        f"{item.decision.decided_by}"
                    )
        # The interpreter's own view of every call the SQL did not return.
        for slug, call in calls.items():
            if call.status != CallStatus.OPEN or slug in shown:
                continue
            superset.checked += 1
            verdict = stage1.judge(call, criteria[slug], profile).verdict
            if verdict != Verdict.NOT_ELIGIBLE:
                superset.failures.append(
                    f"{key} × {slug}: filtered by stage 1a, but the rules say {verdict}"
                )

    checks += [superset, excluded_by, capped, ranked_check]
    results = [Result(case, observed[(case.profile, case.call)]) for case in cases]
    return Report(
        as_of=as_of,
        profiles=len(profiles),
        fixtures=len(fixtures),
        checks=checks,
        results=results,
        problems=problems,
        unanswered=unanswered,
        latency_ms=latency,
        gate=suite["gate"],
        weights_version=stage2.WEIGHTS_VERSION,
        open_calls=sum(1 for f in fixtures.values() if f.shortlistable),
    )
