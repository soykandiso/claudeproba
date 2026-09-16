"""Stages 0–2 for the demo: intake answers to profile, rules, verdict, rank.

Stage 1 is the real rule interpreter (app/matching/hard_filter.py) and the verdict
is the real taxonomy (app/matching/taxonomy.py). What is simulated:

- the intake options and the municipality table stand in for reference data in
  data/ (P2 s22);
- narrative criteria have pre-recorded answers instead of a model call (P2 s29);
- ranking uses four components from config/weights/demo.yaml, not v1 (P2 s27).
"""

import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import yaml

from app.ai.scrub import Scrubber
from app.matching.hard_filter import Range, RuleResult, evaluate, nace_matches
from app.matching.operators import ProfileField
from app.matching.taxonomy import DecidedBy, Decision, Outcome, call_verdict, criterion_verdict
from app.models.enums import CriterionKind, Verdict
from app.web.demo.data import PURPOSES, Citation, Criterion, DemoCall

WEIGHTS_FILE = Path(__file__).resolve().parents[3] / "config" / "weights" / "demo.yaml"

# ---------------------------------------------------------------- intake options

ENTITY_FORMS = {
    "dooel": "ДООЕЛ",
    "doo": "ДОО",
    "ad": "АД",
    "tp": "Трговец поединец",
    "farm": "Земјоделско стопанство",
    "ngo": "Здружение на граѓани",
}

# code: (name, planning region, inside Град Скопје)
MUNICIPALITIES = {
    "centar": ("Центар", "Скопски", True),
    "karpos": ("Карпош", "Скопски", True),
    "gazi-baba": ("Гази Баба", "Скопски", True),
    "cair": ("Чаир", "Скопски", True),
    "ilinden": ("Илинден", "Скопски", False),
    "bitola": ("Битола", "Пелагониски", False),
    "prilep": ("Прилеп", "Пелагониски", False),
    "kumanovo": ("Куманово", "Североисточен", False),
    "tetovo": ("Тетово", "Полошки", False),
    "stip": ("Штип", "Источен", False),
    "ohrid": ("Охрид", "Југозападен", False),
    "strumica": ("Струмица", "Југоисточен", False),
    "veles": ("Велес", "Вардарски", False),
}

EMPLOYEES = {
    "0-1": ("0–1", Range(0, 1)),
    "2-9": ("2–9", Range(2, 9)),
    "10-49": ("10–49", Range(10, 49)),
    "50-249": ("50–249", Range(50, 249)),
    "250+": ("250 и повеќе", Range(250, 1_000_000)),
}

TURNOVER = {
    "lt10": "до 10 милиони МКД",
    "10-50": "10–50 милиони МКД",
    "50-150": "50–150 милиони МКД",
    "gt150": "над 150 милиони МКД",
}

AMOUNTS = {
    "lt1": ("до 1 милион МКД", Range(0, 1_000_000)),
    "1-3": ("1–3 милиони МКД", Range(1_000_000, 3_000_000)),
    "3-10": ("3–10 милиони МКД", Range(3_000_000, 10_000_000)),
    "gt10": ("над 10 милиони МКД", Range(10_000_000, 1_000_000_000)),
}

TIMELINES = {
    "now": "Веднаш",
    "6m": "Во наредните 6 месеци",
    "later": "За повеќе од 6 месеци",
}

NACE_EXAMPLES = (
    "62.01 Компјутерско програмирање",
    "10.71 Производство на леб и свежи пецива",
    "01.13 Одгледување зеленчук",
    "55.10 Хотели и слично сместување",
    "47.11 Трговија на мало во неспецијализирани продавници",
    "25.62 Машинска обработка на метали",
)

DEFAULT_ANSWERS = {
    "entity": "dooel",
    "nace": "62.01 Компјутерско програмирање",
    "municipality": "centar",
    "founded": "2022",
    "employees": "2-9",
    "turnover": "lt10",
    "inv": ["digital", "equipment"],
    "amount": "1-3",
    "timeline": "6m",
    "description": "Софтвер за управување со залихи за мали продавници",
}

_NACE_CODE = re.compile(r"^\s*(\d{2}(?:\.\d{1,2})?)(?!\d)")


def clean_answers(form) -> tuple[dict, dict[str, str]]:
    """Validate the intake form. Returns (answers, errors keyed by field name)."""
    errors: dict[str, str] = {}
    a = {
        "entity": form.get("entity", ""),
        "nace": form.get("nace", "").strip()[:80],
        "municipality": form.get("municipality", ""),
        "founded": form.get("founded", "").strip(),
        "employees": form.get("employees", ""),
        "turnover": form.get("turnover", ""),
        "inv": [v for v in form.getlist("inv") if v in PURPOSES],
        "amount": form.get("amount", ""),
        "timeline": form.get("timeline", ""),
        "description": form.get("description", "").strip()[:300],
    }
    for name, options in (
        ("entity", ENTITY_FORMS),
        ("municipality", MUNICIPALITIES),
        ("employees", EMPLOYEES),
        ("turnover", TURNOVER),
        ("amount", AMOUNTS),
        ("timeline", TIMELINES),
    ):
        if a[name] not in options:
            errors[name] = "Изберете една од понудените можности."
    year = date.today().year
    if not (a["founded"].isdigit() and 1900 <= int(a["founded"]) <= year):
        errors["founded"] = f"Внесете година со четири цифри, од 1900 до {year}."
    if a["nace"] and not _NACE_CODE.match(a["nace"]):
        errors["nace"] = "Почнете со шифрата, на пример 62.01. Ако не ја знаете, оставете празно."
    return a, errors


# ---------------------------------------------------------------- stage 0


@dataclass(frozen=True)
class Profile:
    answers: dict
    nace_code: str | None
    entity_types: frozenset[str]
    age_months: Range
    headcount: Range
    investment: Range
    purposes: frozenset[str]
    municipality: str
    region: str
    in_skopje: bool

    @property
    def rules_view(self) -> dict[ProfileField, object]:
        return {
            ProfileField.ENTITY_TYPE: self.entity_types,
            ProfileField.NACE_CODE: self.nace_code,
            ProfileField.AGE_MONTHS: self.age_months,
            ProfileField.HEADCOUNT: self.headcount,
            ProfileField.INVESTMENT_SIZE_MKD: self.investment,
        }

    @property
    def form_label(self) -> str:
        return ENTITY_FORMS[self.answers["entity"]]

    @property
    def employees_label(self) -> str:
        return EMPLOYEES[self.answers["employees"]][0]

    @property
    def amount_label(self) -> str:
        return AMOUNTS[self.answers["amount"]][0]

    @property
    def size_band(self) -> str | None:
        sizes = self.entity_types & {"micro", "small", "medium", "large"}
        return next(iter(sizes), None)


def normalise(answers: dict, today: date | None = None) -> Profile:
    today = today or date.today()
    year = int(answers["founded"])
    # Only the year is known: founded somewhere between 1 January and 31 December.
    oldest = (today.year - year) * 12 + today.month - 1
    youngest = max(0, oldest - 12)
    employees = EMPLOYEES[answers["employees"]][1]

    form = answers["entity"]
    if form in ("dooel", "doo", "ad"):
        if employees.hi <= 9:
            types = {"micro"}
        elif employees.hi <= 49:
            types = {"small"}
        elif employees.hi <= 249:
            types = {"medium"}
        else:
            types = {"large"}
    else:
        types = {"tp": {"sole_trader"}, "farm": {"farm"}, "ngo": {"ngo"}}[form]

    match = _NACE_CODE.match(answers.get("nace") or "")
    name, region, in_skopje = MUNICIPALITIES[answers["municipality"]]
    return Profile(
        answers=answers,
        nace_code=match.group(1) if match else None,
        entity_types=frozenset(types),
        age_months=Range(youngest, oldest),
        headcount=employees,
        investment=AMOUNTS[answers["amount"]][1],
        purposes=frozenset(answers.get("inv") or ()),
        municipality=name,
        region=region,
        in_skopje=in_skopje,
    )


def applicant_shape(profile: Profile) -> dict[str, str]:
    """What a model would be told about the applicant (docs/matching.md §5)."""
    years = f"{int(profile.age_months.lo // 12)}–{int(profile.age_months.hi // 12) + 1} години"
    return {
        "nace": profile.nace_code or "непознато",
        "size_band": profile.size_band or ", ".join(sorted(profile.entity_types)),
        "region": profile.region,
        "age_band": years,
        "investment_band": profile.amount_label,
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
        ProfileField.AGE_MONTHS: f"основана {profile.answers['founded']}",
        ProfileField.HEADCOUNT: f"{profile.employees_label} вработени",
        ProfileField.ENTITY_TYPE: profile.form_label
        + (f", {_SIZE_WORDS[profile.size_band]}" if profile.size_band else ""),
        ProfileField.NACE_CODE: f"дејност {profile.nace_code}",
        ProfileField.INVESTMENT_SIZE_MKD: profile.amount_label,
    }[c.field]
    if result == RuleResult.UNCLEAR:
        return f"Во профилот: {shown}. Опсегот не е доволен за да се одлучи."
    return f"Во профилот: {shown}."


_SIZE_WORDS = {
    "micro": "микро претпријатие",
    "small": "мало претпријатие",
    "medium": "средно претпријатие",
    "large": "големо претпријатие",
}


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
                note = f"Во профилот: општина {profile.municipality}. Потврдете го седиштето."
        else:
            if c.purpose_any:
                hit = bool(c.purpose_any & profile.purposes)
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
    if not profile.purposes:
        return 0.3, "Не сте навеле што планирате да финансирате."
    common = call.purposes & profile.purposes
    if common:
        words = ", ".join(PURPOSES[p] for p in sorted(common))
        return 1.0, f"Повикот финансира {words}."
    return 0.0, "Повикот не финансира ништо од она што го наведовте."


def _size_fit(call: DemoCall, profile: Profile) -> tuple[float, str]:
    band, inv = call.project_mkd, profile.investment
    if band is None:
        return 0.5, "Повикот не пропишува вредност на проектот."
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
    if profile.answers.get("timeline") == "later" and left < 180:
        return 0.4, "Планирате да започнете по рокот на повикот."
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
