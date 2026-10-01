"""Stage 2: score and rank what stage 1 kept (docs/matching.md §4).

Every component returns a value in [0, 1] **and a reason in Macedonian**. The
reasons are not decoration: the free shortlist prints them under each call, and
they are what makes a ranking explainable a year later.

**Ranking is not eligibility.** Nothing here reads or changes a verdict. A score
orders the calls a company might apply for; whether it may is stage 1's rules and
stage 3's verification. A call the rules exclude is ranked after every other one,
so the shortlist can show it separately with its reason instead of dropping it.

**Missing data scores neutral, and says so.** Most calls do not state a project
size, a co-financing share or a target sector, and many profiles skip those
questions. Such a component returns 0.5 with a reason naming what is missing. A
neutral value moves nothing between two calls that are both silent, and it never
pretends to a fit nobody measured.

**The weights are untuned** (`config/weights/v1.yaml`). They are the design's
starting values. The evaluation suite cannot measure rank quality yet: four open
calls fit in any top five, so "is the right call in the top five" is true of
every ordering. Tune them when the registry and the cases can tell orderings apart.
"""

import datetime as dt
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from app.matching.normalise import Profile
from app.matching.stage1 import CallOutcome
from app.models import Call, EligibilityCriterion
from app.models.enums import Verdict
from app.wording import days_in_words

WEIGHTS_DIR = Path(__file__).resolve().parents[2] / "config" / "weights"
WEIGHTS_VERSION = "v1"

NEUTRAL = 0.5

# How specifically a call names an activity. НКД's finest level is the class, so
# the design's table starts there: a call for "10.71" is more plainly meant for a
# bakery than one for all of manufacturing, which is still a fit, not a miss.
SECTOR_LEVEL = {"section": 0.5, "division": 0.7, "group": 0.85, "class": 1.0}

# Under two weeks is not enough time to assemble an application (matching.md §4).
SHORT_NOTICE_DAYS = 14


@dataclass(frozen=True)
class Part:
    name: str
    value: float
    weight: float
    reason_mk: str


@dataclass(frozen=True)
class Scored:
    outcome: CallOutcome
    score: float
    parts: tuple[Part, ...]
    weights_version: str

    @property
    def call(self) -> Call:
        return self.outcome.call

    @property
    def excluded(self) -> bool:
        return self.outcome.verdict == Verdict.NOT_ELIGIBLE


# ------------------------------------------------------------------ components


def _level(prefix: str) -> str:
    if prefix.isalpha():
        return "section"
    return {2: "division", 4: "group"}.get(len(prefix), "class")


def sector_fit(call: Call, profile: Profile, **_) -> tuple[float, str]:
    """How specifically the call names the applicant's activity.

    Read from `allowed_nace_prefixes`, the same column stage 1a filters on, and
    matched against the same chain of codes, so the two can never disagree about
    whether an activity is covered.
    """
    if not call.allowed_nace_prefixes:
        return NEUTRAL, "Повикот не ограничува дејност."
    if not profile.nace:
        return NEUTRAL, "Дејноста не е внесена во профилот."
    covered = [p for p in call.allowed_nace_prefixes if p in profile.nace_prefixes]
    if not covered:
        return 0.0, f"Дејноста {profile.nace_code} не е меѓу оние за кои е повикот."
    best = max(SECTOR_LEVEL[_level(p)] for p in covered)
    return best, f"Повикот е наменет за дејноста {profile.nace_code}."


def _mkd(amount: float) -> str:
    return f"{amount:,.0f}".replace(",", ".") + " МКД"


def _largest_funded_project(call: Call) -> float | None:
    """The project size the cap pays its full share of: the cap over that share."""
    if call.grant_max_mkd is None:
        return None
    cap = float(call.grant_max_mkd)
    if call.cofinancing_pct is None or float(call.cofinancing_pct) >= 100:
        return cap
    return cap / ((100 - float(call.cofinancing_pct)) / 100)


def size_fit(call: Call, profile: Profile, **_) -> tuple[float, str]:
    """The applicant's investment against what the call pays one applicant.

    **A departure from the design table**, measured on the frozen calls: comparing
    the investment with the grant band put the Economy call — the one a
    manufacturing bakery can actually use — last in its shortlist, because its
    200.000 МКД cap is far below a 3–10 million investment. A cap is not a misfit;
    it means the grant pays part. And a call that states its terms must never rank
    below one that says nothing. So:

    - up to the largest project the cap pays its full share of: 1.0;
    - above it: neutral, the same as a call that names no amount, with a reason
      saying the grant covers only part;
    - below a stated minimum grant: falls linearly to 0 at half the minimum —
      a project too small to qualify is the one real misfit here.
    """
    investment = profile.investment_mkd
    minimum = float(call.grant_min_mkd) if call.grant_min_mkd is not None else None
    largest = _largest_funded_project(call)
    if minimum is None and largest is None:
        return NEUTRAL, "Повикот не наведува износ по барател."
    if investment is None:
        return NEUTRAL, "Не сте навеле приближен износ на инвестицијата."
    if minimum is not None and investment.hi < minimum:
        ratio = minimum / investment.hi if investment.hi else float("inf")
        return (
            max(0.0, 2.0 - ratio),
            f"Инвестицијата е помала од најмалку {_mkd(minimum)} по барател.",
        )
    if largest is not None and investment.lo > largest:
        return (
            NEUTRAL,
            f"Грантот е најмногу {_mkd(float(call.grant_max_mkd))} по барател "
            "и покрива само дел од инвестицијата.",
        )
    return 1.0, "Износот на инвестицијата одговара на износот по барател."


def timeline_fit(call: Call, profile: Profile, *, now: dt.datetime, **_) -> tuple[float, str]:
    """Time left to prepare an application.

    The design also compares the project's length with the call; no call states
    an implementation period yet, so that half waits for a column to read.
    """
    if call.deadline_at is None:
        return NEUTRAL, "Повикот нема краен рок; трае до исцрпување на средствата."
    # Calendar days in Skopje, as the deadline above it is said: a call closing at
    # 23:59 today is «рокот истекува денес», not «0 дена» (docs/design.md F17).
    skopje = ZoneInfo("Europe/Skopje")
    days = max((call.deadline_at.astimezone(skopje).date() - now.astimezone(skopje).date()).days, 0)
    if days < SHORT_NOTICE_DAYS:
        # The screen's own words (app/wording.py). Only the reason changes, not the
        # score, so no weights version moves.
        words = days_in_words(days)
        return 0.2, f"{words[:1].upper()}{words[1:]}, кратко за подготовка."
    return 1.0, f"До рокот {_days_left(days)}."


def _days_left(days: int) -> str:
    # Macedonian agrees with the last digit: 1, 21, 31 … take the singular, 11 does not.
    if days % 10 == 1 and days % 100 != 11:
        return f"останува {days} ден"
    return f"остануваат {days} дена"


def cofinancing_fit(call: Call, profile: Profile, **_) -> tuple[float, str]:
    """The applicant's own share against the call's. Below it is fixable, so 0.2, not 0."""
    required, offered = call.cofinancing_pct, profile.cofinancing_pct
    if required is None:
        return NEUTRAL, "Повикот не наведува сопствено учество."
    if offered is None:
        return NEUTRAL, f"Повикот бара {float(required):g}% сопствено учество; не сте навеле колку."
    said = f"Повикот бара {float(required):g}% сопствено учество, а наведовте {offered:g}%."
    return (1.0 if offered >= float(required) else 0.2), said


def soft_criteria(
    call: Call, profile: Profile, *, soft: list[EligibilityCriterion], **_
) -> tuple[float, str]:
    """The call's stated preferences — extra points, never an exclusion.

    No profile answer can meet one yet (women-owned, youth, less-developed region
    are not asked), so the value stays neutral and the reason names them, which is
    still worth reading on a shortlist.
    """
    if not soft:
        return NEUTRAL, "Повикот не наведува предности што носат бодови."
    names = "; ".join(c.label_mk for c in soft)
    return NEUTRAL, f"Повикот дава предност на: {names}. Профилот не кажува дали ги исполнувате."


def semantic_fit(call: Call, profile: Profile, **_) -> tuple[float, str]:
    """Not computed: where the description's embedding is made is still open (§4)."""
    return NEUTRAL, "Сличноста на описот на проектот со повикот сè уште не се пресметува."


COMPONENTS: dict[str, Callable[..., tuple[float, str]]] = {
    "sector_fit": sector_fit,
    "size_fit": size_fit,
    "timeline_fit": timeline_fit,
    "cofinancing_fit": cofinancing_fit,
    "soft_criteria": soft_criteria,
    "semantic_fit": semantic_fit,
}


# ------------------------------------------------------------------ weights


@cache
def weights(version: str = WEIGHTS_VERSION) -> dict[str, float]:
    """One weights file, refused unless it names every component and sums to 1."""
    path = WEIGHTS_DIR / f"{version}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("version") != version:
        raise ValueError(f"{path.name}: says version {raw.get('version')!r}, not {version!r}")
    found = {name: float(value) for name, value in raw["weights"].items()}
    if set(found) != set(COMPONENTS):
        raise ValueError(f"{path.name}: components {sorted(found)} ≠ {sorted(COMPONENTS)}")
    if any(value < 0 for value in found.values()):
        raise ValueError(f"{path.name}: a negative weight")
    if abs(sum(found.values()) - 1.0) > 1e-9:
        raise ValueError(f"{path.name}: weights sum to {sum(found.values())}, not 1.0")
    return found


# ------------------------------------------------------------------ the stage


def score(
    outcome: CallOutcome,
    profile: Profile,
    now: dt.datetime,
    version: str = WEIGHTS_VERSION,
) -> Scored:
    w = weights(version)
    soft = list(outcome.preferences)
    parts = []
    for name, component in COMPONENTS.items():
        value, reason = component(outcome.call, profile, now=now, soft=soft)
        parts.append(Part(name, min(1.0, max(0.0, value)), w[name], reason))
    total = sum(p.value * p.weight for p in parts)
    return Scored(outcome, round(total, 4), tuple(parts), version)


_LAST = dt.datetime.max.replace(tzinfo=dt.UTC)


def rank(
    outcomes: Iterable[CallOutcome],
    profile: Profile,
    now: dt.datetime,
    version: str = WEIGHTS_VERSION,
) -> list[Scored]:
    """Highest score first; an earlier deadline breaks a tie; excluded calls last.

    The verdict is shown, not sorted on — except `not_eligible`, which goes to the
    end so a call the rules exclude never sits above one a company can apply for.
    """
    scored = [score(o, profile, now, version) for o in outcomes]
    return sorted(scored, key=lambda s: (s.excluded, -s.score, s.call.deadline_at or _LAST))
