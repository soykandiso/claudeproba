"""Stages 0–2 for the demo: intake answers to profile, rules, verdict, rank.

Stage 1 is the real rule interpreter (app/matching/hard_filter.py) and the verdict
is the real taxonomy (app/matching/taxonomy.py). What is simulated:

- nothing about intake: since P2 s23 the demo asks the real questions
  (app/matching/intake.py) over the real reference data and runs the real stage 0;
- narrative criteria have pre-recorded answers instead of a model call (P2 s29);
- ranking uses four components from config/weights/demo.yaml, not v1 (P2 s27).
"""

from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import yaml

from app.ai.scrub import Scrubber
from app.matching import intake
from app.matching.hard_filter import RuleResult, evaluate, nace_matches
from app.matching.intake import PURPOSES
from app.matching.normalise import Profile
from app.matching.operators import ProfileField
from app.matching.taxonomy import DecidedBy, Decision, Outcome, call_verdict, criterion_verdict
from app.models.enums import CriterionKind, Verdict
from app.web.demo.data import Citation, Criterion, DemoCall

WEIGHTS_FILE = Path(__file__).resolve().parents[3] / "config" / "weights" / "demo.yaml"

# ------------------------------------------------- intake, stage 0: the real ones

# Until P2 s23 the demo had its own thirteen municipalities, its own bands and its
# own `normalise`. It now asks the real questions over the real reference data and
# runs the real stage 0; what is left here is presentation and the simulated parts.

DEFAULT_ANSWERS = {
    "entity": "dooel",
    "nace": "62.01 Компјутерско програмирање",
    "municipality": "MK00814",  # Центар, Скопски регион, inside Град Скопје
    "founded": "2022",
    "employees": "2-9",
    "turnover": "lt10",
    "inv": ["digital", "equipment"],
    "amount": "1-3",
    "cofinancing": "30",
    "timeline_months": "9",
    "description": "Софтвер за управување со залихи за мали продавници",
}


UNKNOWN = "непознато"


def applicant_shape(profile: Profile) -> dict[str, str]:
    """What a model would be told about the applicant (docs/matching.md §5).

    Every value here is a band, a code or a region — never a name, a number that
    identifies, or the free text (CLAUDE.md invariant 4). An answer that was not
    given stays unknown rather than being filled in with a plausible middle.
    """
    age = profile.age_months
    return {
        "nace": profile.nace_code or UNKNOWN,
        "size_band": profile.size_band or ", ".join(sorted(profile.entity_types)) or UNKNOWN,
        "region": intake.region_label(profile) or UNKNOWN,
        "age_band": f"{int(age.lo // 12)}–{int(age.hi // 12) + 1} години" if age else UNKNOWN,
        "investment_band": intake.amount_label(profile) or UNKNOWN,
    }


def scrubbed_description(profile: Profile) -> str:
    return Scrubber().scrub(profile.answers.get("description") or "")


# ---------------------------------------------------------------- stage 1


@dataclass(frozen=True)
class CriterionResult:
    criterion: Criterion
    decision: Decision
    verdict: Verdict
    citation: Citation | None
    note: str  # what in the profile (or the recorded check) led here


def _profile_note(c: Criterion, profile: Profile, result: RuleResult) -> str:
    if result == RuleResult.UNCLEAR and c.field == ProfileField.NACE_CODE and not profile.nace_code:
        return "Профилот не ја содржи шифрата на дејноста."
    shown = {
        ProfileField.AGE_MONTHS: f"основана {profile.answers.get('founded')}",
        ProfileField.HEADCOUNT: f"{intake.employees_label(profile)} вработени",
        ProfileField.ENTITY_TYPE: ", ".join(
            x for x in (intake.form_label(profile), intake.size_label(profile)) if x
        ),
        ProfileField.NACE_CODE: f"дејност {profile.nace_code}",
        ProfileField.INVESTMENT_SIZE_MKD: intake.amount_label(profile),
    }[c.field]
    if result == RuleResult.UNCLEAR:
        return f"Во профилот: {shown}. Опсегот не е доволен за да се одлучи."
    return f"Во профилот: {shown}."


def check(call: DemoCall, profile: Profile) -> list[CriterionResult]:
    results = []
    for c in call.criteria:
        if c.kind == CriterionKind.HARD_STRUCTURED:
            rule = evaluate(c, profile.rules_view)
            decision = Decision(Outcome(rule.value), DecidedBy.RULE)
            note = _profile_note(c, profile, rule)
        elif c.kind == CriterionKind.APPLICANT_ATTEST:
            decision = Decision(Outcome.ATTEST, DecidedBy.APPLICANT)
            note = "Го потврдувате вие при пријавата."
            if c.key == "seat":
                seat = intake.municipality_label(profile) or "не е внесена"
                note = f"Во профилот: општина {seat}. Потврдете го седиштето."
        else:
            if c.purpose_any:
                hit = bool(c.purpose_any & intake.purposes(profile))
                outcome = Outcome.SATISFIED if hit else Outcome.NOT_SATISFIED
            else:
                outcome = Outcome(c.recorded)
            if outcome == Outcome.SATISFIED and c.confidence < 0.7:
                outcome = Outcome.UNCLEAR  # low confidence downgrades (matching.md §5)
            decision = Decision(outcome, DecidedBy.MODEL)
            note = c.model_note
        citation = call.citation(c)
        verdict = criterion_verdict(decision)
        if citation is None:
            # No citation, no claim: whatever was decided, it cannot be shown as settled.
            decision = Decision(Outcome.UNCLEAR, decision.decided_by)
            verdict = Verdict.NEEDS_VERIFICATION
        results.append(CriterionResult(c, decision, verdict, citation, note))
    return results


# ---------------------------------------------------------------- stage 2


@cache
def weights() -> tuple[str, dict[str, float]]:
    raw = yaml.safe_load(WEIGHTS_FILE.read_text(encoding="utf-8"))
    w = {k: float(v) for k, v in raw["weights"].items()}
    if abs(sum(w.values()) - 1.0) > 1e-9:
        raise ValueError(f"{WEIGHTS_FILE.name}: weights sum to {sum(w.values())}, not 1.0")
    return raw["version"], w


def _sector_fit(call: DemoCall, profile: Profile) -> tuple[float, str]:
    if not call.priority_nace:
        return 0.5, "Повикот е отворен за сите дејности."
    code = profile.nace_code
    if not code:
        return 0.3, "Дејноста не е внесена во профилот."
    best = 0.0
    for prefix in call.priority_nace:
        if nace_matches(code, prefix):
            level = 0.5 if prefix.isalpha() else {2: 0.7, 4: 0.85}.get(len(prefix), 1.0)
            best = max(best, level)
    if best:
        return best, "Дејноста е меѓу оние на кои повикот е наменет."
    return 0.0, "Дејноста не е меѓу оние на кои повикот е наменет."


def _purpose_fit(call: DemoCall, profile: Profile) -> tuple[float, str]:
    chosen = intake.purposes(profile)
    if not chosen:
        return 0.3, "Не сте навеле што планирате да финансирате."
    common = call.purposes & chosen
    if common:
        words = ", ".join(PURPOSES[p] for p in sorted(common))
        return 1.0, f"Повикот финансира {words}."
    return 0.0, "Повикот не финансира ништо од она што го наведовте."


def _size_fit(call: DemoCall, profile: Profile) -> tuple[float, str]:
    band, inv = call.project_mkd, profile.investment_mkd
    if band is None:
        return 0.5, "Повикот не пропишува вредност на проектот."
    if inv is None:
        return 0.3, "Не сте навеле приближен износ на инвестицијата."
    if inv.hi >= band.lo and inv.lo <= band.hi:
        return 1.0, "Износот на инвестицијата одговара на големината на проектите во повикот."
    if inv.hi < band.lo:
        ratio = inv.hi / band.lo
        text = "Инвестицијата е помала од проектите што ги финансира повикот."
    else:
        ratio = band.hi / inv.lo
        text = "Инвестицијата е поголема од проектите што ги финансира повикот."
    return max(0.0, 2 * ratio - 1), text


def _timeline_fit(call: DemoCall, profile: Profile, today: date) -> tuple[float, str]:
    left = (call.deadline - today).days
    if left < 14:
        return 0.2, "До рокот има помалку од 14 дена, што е кратко за подготовка."
    months = profile.timeline_months
    if months and months * 30 > left + 365:
        return 0.4, "Проектот трае подолго отколку што повикот остава време."
    return 1.0, "Има доволно време за подготовка до рокот."


@dataclass(frozen=True)
class Match:
    call: DemoCall
    verdict: Verdict
    results: list[CriterionResult]
    score: float
    breakdown: list[tuple[str, float, str]]

    @property
    def open_items(self) -> list[CriterionResult]:
        return [r for r in self.results if r.verdict != Verdict.ELIGIBLE]


def match(call: DemoCall, profile: Profile, today: date | None = None) -> Match:
    today = today or date.today()
    results = check(call, profile)
    verdict = call_verdict(r.decision for r in results)
    _, w = weights()
    parts = {
        "sector_fit": _sector_fit(call, profile),
        "purpose_fit": _purpose_fit(call, profile),
        "size_fit": _size_fit(call, profile),
        "timeline_fit": _timeline_fit(call, profile, today),
    }
    breakdown = [(name, value, reason) for name, (value, reason) in parts.items()]
    score = sum(w[name] * value for name, value, _ in breakdown)
    return Match(call, verdict, results, score, breakdown)


def shortlist(calls: list[DemoCall], profile: Profile, today: date | None = None) -> list[Match]:
    """Open calls ranked by score. Verdict does not rank: it is shown, not sorted on."""
    today = today or date.today()
    matches = [match(c, profile, today) for c in calls if c.deadline >= today]
    return sorted(matches, key=lambda m: (-m.score, m.call.deadline))
