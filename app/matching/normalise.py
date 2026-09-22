"""Stage 0: intake answers → the profile the rules operate on (docs/matching.md §2).

Deterministic, no database, no model, under a millisecond. Everything it cannot
work out is `None`, and `None` reaches the rule interpreter as *unclear* — which
asks the applicant rather than excluding them (CLAUDE.md invariant 3). Nothing in
this module may return a value it is not sure of; a guessed municipality is a
wrong region is a wrong shortlist that nobody ever disputes.

The answers arrive as the strings a form posts. Validation lives with the form
(P2 s23); this module is total over anything at all, so a stale or hand-built
payload can never raise in a web request.

**Bands, not exact numbers.** Intake asks for 2–9 employees and a founding year,
not a headcount and a date, because the brief minimises what is collected. Every
number here is therefore a closed `Range`, and `hard_filter` judges a range
conservatively. The bands are the ones the demo established and the user
approved on 16.09.2026; P2 s23 renders these, it does not invent its own.
"""

import datetime as dt
from dataclasses import dataclass

from app.matching import reference
from app.matching.hard_filter import Range
from app.matching.operators import ProfileField
from app.matching.reference import Municipality, Nace
from app.models.enums import EntityType

# --------------------------------------------------------------- the vocabulary


@dataclass(frozen=True)
class Band:
    """One option of a banded question: what it is called, and what it means."""

    key: str
    label_mk: str
    values: Range


def _bands(*rows: tuple[str, str, float, float]) -> dict[str, Band]:
    return {key: Band(key, label, Range(lo, hi)) for key, label, lo, hi in rows}


# An open-ended band still needs a top: a range is closed by definition. These
# ceilings are far above any applicant the platform will see, and a criterion
# that would be decided by one is decided as unclear instead, which asks.
MANY_EMPLOYEES = 1_000_000
HUGE_MKD = 100_000_000_000.0

ENTITY_FORMS = {
    "dooel": "ДООЕЛ",
    "doo": "ДОО",
    "ad": "АД",
    "tp": "Трговец поединец",
    "farm": "Земјоделско стопанство",
    "ngo": "Здружение на граѓани",
}

HEADCOUNT_BANDS = _bands(
    ("0-1", "0–1", 0, 1),
    ("2-9", "2–9", 2, 9),
    ("10-49", "10–49", 10, 49),
    ("50-249", "50–249", 50, 249),
    ("250+", "250 и повеќе", 250, MANY_EMPLOYEES),
)

TURNOVER_BANDS = _bands(
    ("lt10", "до 10 милиони МКД", 0, 10_000_000),
    ("10-50", "10–50 милиони МКД", 10_000_000, 50_000_000),
    ("50-150", "50–150 милиони МКД", 50_000_000, 150_000_000),
    ("gt150", "над 150 милиони МКД", 150_000_000, HUGE_MKD),
)

INVESTMENT_BANDS = _bands(
    ("lt1", "до 1 милион МКД", 0, 1_000_000),
    ("1-3", "1–3 милиони МКД", 1_000_000, 3_000_000),
    ("3-10", "3–10 милиони МКД", 3_000_000, 10_000_000),
    ("gt10", "над 10 милиони МКД", 10_000_000, HUGE_MKD),
)

# The denar has been pegged to the euro since 2002; a rate that moves in the
# third decimal cannot move an SME band, so a constant is honest here.
MKD_PER_EUR = 61.5

# EU SME definition (Recommendation 2003/361/EC), the one every call in the
# country ultimately refers back to: headcount AND turnover, not headcount alone.
SME_BANDS = (
    (EntityType.MICRO, 9, 2_000_000 * MKD_PER_EUR),
    (EntityType.SMALL, 49, 10_000_000 * MKD_PER_EUR),
    (EntityType.MEDIUM, 249, 50_000_000 * MKD_PER_EUR),
)

# Which entity types a legal form implies, beyond its size band. A size band is
# added for the commercial forms only: a call that writes `not_in [micro]` means
# small companies, and an association or a farm is neither excluded nor included
# by that sentence. Erring the other way would exclude them silently, which is
# the failure this codebase is built to avoid (docs/matching.md §3).
FORM_TYPES: dict[str, tuple[frozenset[EntityType], bool]] = {
    "dooel": (frozenset(), True),
    "doo": (frozenset(), True),
    "ad": (frozenset(), True),
    "tp": (frozenset({EntityType.SOLE_TRADER}), True),
    "farm": (frozenset({EntityType.FARM}), False),
    "ngo": (frozenset({EntityType.NGO}), False),
}


SIZE_TYPES = frozenset(
    t.value for t in (EntityType.MICRO, EntityType.SMALL, EntityType.MEDIUM, EntityType.LARGE)
)


# ------------------------------------------------------------------ the profile


@dataclass(frozen=True)
class Profile:
    """One applicant as the matching engine sees them. No identity data, by shape.

    Nothing here names a company or a person: `app/ai/gateway.py` scrubs at the
    boundary, but a profile that never carries a name cannot leak one either
    (CLAUDE.md invariant 4). `project_description` is the applicant's own prose
    and is the one free-text field, so it is the one the scrubber must still see.
    """

    answers: dict
    entity_types: frozenset[str]
    nace: Nace | None
    municipality: Municipality | None
    age_months: Range | None
    headcount: Range | None
    turnover_mkd: Range | None
    investment_mkd: Range | None
    cofinancing_pct: float | None
    timeline_months: int | None
    project_description: str
    reference_version: str

    @property
    def nace_code(self) -> str | None:
        return self.nace.code if self.nace else None

    @property
    def nace_prefixes(self) -> tuple[str, ...]:
        """Every code a call could name that would cover this applicant."""
        return self.nace.chain if self.nace else ()

    @property
    def municipality_code(self) -> str | None:
        return self.municipality.code if self.municipality else None

    @property
    def region_code(self) -> str | None:
        return self.municipality.region_code if self.municipality else None

    @property
    def in_city_of_skopje(self) -> bool:
        """Град Скопје funds its own ten municipalities, which is not the Skopje region."""
        return bool(self.municipality and self.municipality.city_of_skopje)

    @property
    def size_band(self) -> str | None:
        """micro / small / medium / large, when the answers settle it."""
        return next(iter(self.entity_types & SIZE_TYPES), None)

    @property
    def rules_view(self) -> dict[ProfileField, object]:
        """The mapping `hard_filter.evaluate` reads. Absent key = unknown = unclear."""
        view: dict[ProfileField, object] = {ProfileField.ENTITY_TYPE: self.entity_types}
        if self.nace:
            view[ProfileField.NACE_CODE] = self.nace.code
        if self.age_months:
            view[ProfileField.AGE_MONTHS] = self.age_months
        if self.headcount:
            view[ProfileField.HEADCOUNT] = self.headcount
        if self.investment_mkd:
            view[ProfileField.INVESTMENT_SIZE_MKD] = self.investment_mkd
        return view


# ------------------------------------------------------------------ the pieces


def age_months(founded_year: object, today: dt.date) -> Range | None:
    """Months since founding, as a range: intake asks for a year, not a date.

    A company founded in 2022, asked in September 2026, is between 44 and 56
    months old. A criterion that needs it to be over 48 gets *unclear* and the
    applicant is asked for the date — which is the right answer, not a rounding.
    """
    try:
        year = int(str(founded_year).strip())
    except (TypeError, ValueError):
        return None
    if not 1900 <= year <= today.year:
        return None
    oldest = (today.year - year) * 12 + today.month - 1
    return Range(max(0, oldest - 12), oldest)


def sme_band(headcount: Range | None, turnover: Range | None) -> EntityType | None:
    """The EU SME size band, or None when the answers do not settle it.

    Headcount decides, and turnover can only push the band *up*: a company of
    four people turning over more than 150 million МКД is above the micro
    ceiling of €2 million however few people it employs. Turnover never pulls a
    band down — the definition is an AND, not a best-of.
    """
    if headcount is None:
        return None
    for band, max_headcount, max_turnover_mkd in SME_BANDS:
        if headcount.hi > max_headcount:
            continue
        if turnover is not None and turnover.lo > max_turnover_mkd:
            continue  # the whole band is above this ceiling: it is at least the next size
        return band
    return EntityType.LARGE


def entity_types(form: object, headcount: Range | None, turnover: Range | None) -> frozenset[str]:
    """Every entity type a call could name that this applicant is.

    A trader is a sole trader *and* a size band; a company is a size band. When
    the size cannot be worked out, the set holds only what is certain.
    """
    declared, sized = FORM_TYPES.get(str(form), (frozenset(), False))
    types = set(declared)
    if sized:
        band = sme_band(headcount, turnover)
        if band is not None:
            types.add(band)
    return frozenset(t.value for t in types)


def _band(bands: dict[str, Band], key: object) -> Range | None:
    band = bands.get(str(key))
    return band.values if band else None


def _percentage(value: object) -> float | None:
    try:
        number = float(str(value).strip().rstrip("%").replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if 0.0 <= number <= 100.0 else None


def _months(value: object) -> int | None:
    try:
        months = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return months if 0 < months <= 120 else None


# ------------------------------------------------------------------ stage 0


def normalise(answers: dict, today: dt.date | None = None) -> Profile:
    """Intake answers → `Profile`. Total: any dict at all produces a profile.

    An answer that is missing, unrecognised or out of range becomes None rather
    than an error, because the alternative — a 500 on the intake form, or a
    plausible default — is worse than a criterion that asks.
    """
    today = today or dt.date.today()
    headcount = _band(HEADCOUNT_BANDS, answers.get("employees"))
    turnover = _band(TURNOVER_BANDS, answers.get("turnover"))
    return Profile(
        answers=answers,
        entity_types=entity_types(answers.get("entity"), headcount, turnover),
        nace=reference.resolve_nace(answers.get("nace")),
        municipality=reference.resolve_municipality(answers.get("municipality")),
        age_months=age_months(answers.get("founded"), today),
        headcount=headcount,
        turnover_mkd=turnover,
        investment_mkd=_band(INVESTMENT_BANDS, answers.get("amount")),
        cofinancing_pct=_percentage(answers.get("cofinancing")),
        timeline_months=_months(answers.get("timeline_months")),
        project_description=str(answers.get("description") or "").strip(),
        reference_version=reference.version(),
    )
