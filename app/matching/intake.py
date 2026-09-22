"""The intake questionnaire: what is asked, and what an answer has to look like.

One module, so that the page, the tests and any later channel (a pasted profile, a
phone intake taken by hand) ask the same questions in the same words. The bands
themselves are not defined here — they are `app/matching/normalise.py`'s, and the
lists are `app/matching/reference.py`'s over `data/`. This module only says which
of them are asked, in what order, and what a bad answer is told.

**Almost nothing is required.** The roadmap's acceptance for this form is that a
real person finishes it in under three minutes, and every question that can be
skipped is seconds back. It costs nothing in correctness either: an answer that is
not given is `None` in stage 0, and `None` is *unclear*, which asks the applicant
rather than excluding them (CLAUDE.md invariant 3). Four questions are required
because below them there is no shortlist at all, only a list of every open call.

**An activity we cannot resolve is an error, not a silence.** Every other unknown
degrades quietly, but a person who typed their НКД code and got no match would
otherwise never learn that the field they cared most about was discarded.
"""

import datetime as dt
from dataclasses import dataclass, field

from app.matching import reference
from app.matching.normalise import (
    ENTITY_FORMS,
    HEADCOUNT_BANDS,
    INVESTMENT_BANDS,
    TURNOVER_BANDS,
    Band,
)

MAX_DESCRIPTION = 300
MAX_NACE = 120
MAX_TIMELINE_MONTHS = 120

# What the money is for. Stage 0 does not read this yet — no rule operator takes
# it — but scoring does (P2 s27, `purpose_fit`), and it is the one question that
# lets a person say what they are actually trying to do in one tap.
PURPOSES = {
    "digital": "дигитализација",
    "equipment": "опрема и машини",
    "jobs": "нови вработувања",
    "rnd": "истражување и развој",
    "green": "енергетска ефикасност",
    "export": "извоз и нови пазари",
}


# How a size band is said to the applicant. The band itself is worked out by
# `normalise.sme_band` from headcount and turnover; these are only its words.
SIZE_WORDS = {
    "micro": "микро претпријатие",
    "small": "мало претпријатие",
    "medium": "средно претпријатие",
    "large": "големо претпријатие",
    "sole_trader": "трговец поединец",
    "farm": "земјоделско стопанство",
    "ngo": "здружение на граѓани",
}

# ------------------------------------------------------------------ questions


@dataclass(frozen=True)
class Question:
    """One question, as the form renders it and as the tests read it."""

    key: str
    label_mk: str
    kind: str  # select | activity | year | number | percent | checkboxes | text
    section_mk: str = ""
    hint_mk: str = ""
    required: bool = False
    options: tuple[tuple[str, str], ...] = ()
    groups: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = field(default=())
    suffix_mk: str = ""


def _band_options(bands: dict[str, Band]) -> tuple[tuple[str, str], ...]:
    return tuple((b.key, b.label_mk) for b in bands.values())


def municipality_groups() -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """The 80 municipalities under their eight planning regions, both in name order.

    Grouped because a flat list of eighty is a scroll, and because the region is
    what most calls actually name. Град Скопје is *not* a region (its ten
    municipalities sit inside Скопски), so it gets no group of its own here; the
    distinction lives on the profile, not in the picker.
    """
    regions = reference.regions()
    by_region: dict[str, list[tuple[str, str]]] = {code: [] for code in regions}
    for m in reference.municipalities().values():
        by_region[m.region_code].append((m.code, m.name_mk))
    return tuple(
        (regions[code].name_mk, tuple(sorted(rows, key=lambda r: r[1])))
        for code, rows in sorted(by_region.items(), key=lambda kv: regions[kv[0]].name_mk)
    )


# The three things a person is asked about, in the order they can answer them
# without looking anything up: the company, what it does, what it wants to do.
SECTION_COMPANY = "Фирмата"
SECTION_ACTIVITY = "Дејноста"
SECTION_PROJECT = "Проектот"


def questions() -> tuple[Question, ...]:
    """The questionnaire, in the order it is asked.

    Built on each call rather than at import so a reference-data reload during
    development shows up without restarting; the lists underneath are cached.
    """
    return (
        Question(
            key="entity",
            label_mk="Вид на субјект",
            kind="select",
            section_mk=SECTION_COMPANY,
            required=True,
            options=tuple(ENTITY_FORMS.items()),
        ),
        Question(
            key="municipality",
            label_mk="Општина на седиштето",
            kind="select",
            section_mk=SECTION_COMPANY,
            required=True,
            groups=municipality_groups(),
        ),
        Question(
            key="founded",
            label_mk="Година на основање",
            kind="year",
            section_mk=SECTION_COMPANY,
            required=True,
            hint_mk="Само годината. Повиците за новоосновани се одлучуваат по месеци, "
            "па ако е граничен случај ќе ве прашаме за точниот датум.",
        ),
        Question(
            key="employees",
            label_mk="Број на вработени",
            kind="select",
            section_mk=SECTION_COMPANY,
            required=True,
            options=_band_options(HEADCOUNT_BANDS),
        ),
        Question(
            key="nace",
            label_mk="Главна дејност",
            kind="activity",
            section_mk=SECTION_ACTIVITY,
            hint_mk="Шифрата по НКД е во решението од Централниот регистар. Може и да "
            "пребарувате по име на дејноста.",
        ),
        Question(
            key="turnover",
            label_mk="Годишен промет, минатата година",
            kind="select",
            section_mk=SECTION_ACTIVITY,
            options=_band_options(TURNOVER_BANDS),
        ),
        Question(
            key="inv",
            label_mk="Што планирате да финансирате",
            kind="checkboxes",
            section_mk=SECTION_PROJECT,
            options=tuple(PURPOSES.items()),
        ),
        Question(
            key="amount",
            label_mk="Приближен износ на инвестицијата",
            kind="select",
            section_mk=SECTION_PROJECT,
            options=_band_options(INVESTMENT_BANDS),
        ),
        Question(
            key="cofinancing",
            label_mk="Колку можете да вложите од свои средства",
            kind="percent",
            section_mk=SECTION_PROJECT,
            suffix_mk="%",
            hint_mk="Речиси секој повик бара сопствено учество. Ако не знаете, оставете празно.",
        ),
        Question(
            key="timeline_months",
            label_mk="За колку месеци планирате да го завршите проектот",
            kind="number",
            section_mk=SECTION_PROJECT,
            suffix_mk="месеци",
        ),
        Question(
            key="description",
            label_mk="Опишете го проектот во неколку зборови",
            kind="text",
            section_mk=SECTION_PROJECT,
            hint_mk="Не внесувајте имиња, адреси или телефони. Ако ги внесете, се "
            "бришат пред текстот да стигне до автоматската анализа.",
        ),
    )


def sections() -> tuple[tuple[str, tuple[Question, ...]], ...]:
    """The questionnaire grouped into the three blocks the page shows."""
    grouped: dict[str, list[Question]] = {}
    for q in questions():
        grouped.setdefault(q.section_mk, []).append(q)
    return tuple((title, tuple(rows)) for title, rows in grouped.items())


def question(key: str) -> Question:
    """One question by key, for a partial that renders a single field."""
    return next(q for q in questions() if q.key == key)


# ------------------------------------------------- the answers, said back

# What the platform made of an intake, in the words the applicant used. It lives
# next to the questions rather than in a template because three screens say it —
# the review page, the shortlist header and the draft application documents — and
# they must not drift into three different accounts of the same profile.


def form_label(p) -> str | None:
    return ENTITY_FORMS.get(p.answers.get("entity", ""))


def size_label(p) -> str | None:
    return SIZE_WORDS.get(p.size_band or "") or next(
        (SIZE_WORDS[t] for t in sorted(p.entity_types) if t in SIZE_WORDS), None
    )


def band_label(bands: dict[str, Band], p, key: str) -> str | None:
    band = bands.get(p.answers.get(key, ""))
    return band.label_mk if band else None


def employees_label(p) -> str | None:
    return band_label(HEADCOUNT_BANDS, p, "employees")


def amount_label(p) -> str | None:
    return band_label(INVESTMENT_BANDS, p, "amount")


def municipality_label(p) -> str | None:
    return p.municipality.name_mk if p.municipality else None


def region_label(p) -> str | None:
    region = reference.regions().get(p.region_code or "")
    return region.name_mk if region else None


def seat_label(p) -> str | None:
    """Municipality, region, and whether Град Скопје funds it — which is not the region."""
    if not p.municipality:
        return None
    parts = [p.municipality.name_mk]
    region = region_label(p)
    if region:
        parts.append(f"{region} регион")
    if p.in_city_of_skopje:
        parts.append("во Град Скопје")
    return ", ".join(parts)


def purposes(p) -> frozenset[str]:
    """What the money is for. Not on `Profile`: no rule operator reads it yet."""
    return frozenset(k for k in p.answers.get("inv") or () if k in PURPOSES)


def purpose_words(p) -> str | None:
    return ", ".join(PURPOSES[k] for k in sorted(purposes(p))) or None


def describe(p) -> list[tuple[str, str | None]]:
    """Every answer as a label and a value, with None for what was not answered."""
    age = None
    if p.age_months:
        founded = p.answers.get("founded")
        age = f"{int(p.age_months.lo)}–{int(p.age_months.hi)} месеци, основана {founded}"
    return [
        ("Вид на субјект", ", ".join(x for x in (form_label(p), size_label(p)) if x) or None),
        ("Дејност", f"{p.nace.code} {p.nace.name_mk}" if p.nace else None),
        ("Седиште", seat_label(p)),
        ("Старост", age),
        ("Вработени", employees_label(p)),
        ("Годишен промет", band_label(TURNOVER_BANDS, p, "turnover")),
        ("Намена", purpose_words(p)),
        ("Износ на инвестицијата", amount_label(p)),
        ("Сопствено учество", f"{p.cofinancing_pct:g}%" if p.cofinancing_pct is not None else None),
        ("Рок на проектот", f"{p.timeline_months} месеци" if p.timeline_months else None),
    ]


# ----------------------------------------------------------------- validation

PICK_ONE = "Изберете една од понудените можности."
NACE_UNKNOWN = (
    "Не ја препознаваме оваа дејност. Внесете ја шифрата по НКД, на пример 62.01, "
    "или изберете од предложените."
)


def _year_error(value: str, today: dt.date) -> str | None:
    if not (value.isdigit() and len(value) == 4 and 1900 <= int(value) <= today.year):
        return f"Внесете година со четири цифри, од 1900 до {today.year}."
    return None


def _percent_error(value: str) -> str | None:
    try:
        number = float(value.replace(",", "."))
    except ValueError:
        return "Внесете број од 0 до 100."
    return None if 0 <= number <= 100 else "Внесете број од 0 до 100."


def _months_error(value: str) -> str | None:
    if not value.isdigit() or not 0 < int(value) <= MAX_TIMELINE_MONTHS:
        return f"Внесете број на месеци, од 1 до {MAX_TIMELINE_MONTHS}."
    return None


def clean(form, today: dt.date | None = None) -> tuple[dict, dict[str, str]]:
    """A posted form → (answers for stage 0, errors keyed by question).

    The answers are returned whether or not there are errors, so the page can be
    re-rendered with what the person typed still in it. Every value is a string
    or a list of strings, exactly as `normalise()` expects — stage 0 does the
    interpreting, this only refuses what it can explain.
    """
    today = today or dt.date.today()
    get = form.get
    answers = {
        "entity": get("entity", "").strip(),
        "municipality": get("municipality", "").strip(),
        "founded": get("founded", "").strip(),
        "employees": get("employees", "").strip(),
        "nace": get("nace", "").strip()[:MAX_NACE],
        "turnover": get("turnover", "").strip(),
        "inv": [v for v in form.getlist("inv") if v in PURPOSES],
        "amount": get("amount", "").strip(),
        "cofinancing": get("cofinancing", "").strip().rstrip("%").strip(),
        "timeline_months": get("timeline_months", "").strip(),
        "description": get("description", "").strip()[:MAX_DESCRIPTION],
    }

    year_message = f"Внесете година со четири цифри, од 1900 до {today.year}."
    blank_message = {"entity": PICK_ONE, "municipality": PICK_ONE, "employees": PICK_ONE}
    required = {q.key for q in questions() if q.required}
    errors: dict[str, str] = {}

    def check(key: str, message: str | None) -> None:
        """Record a message for an answer that is given and wrong, or required and blank."""
        if answers[key]:
            if message:
                errors[key] = message
        elif key in required:
            errors[key] = blank_message.get(key, year_message)

    check("entity", None if answers["entity"] in ENTITY_FORMS else PICK_ONE)
    check("employees", None if answers["employees"] in HEADCOUNT_BANDS else PICK_ONE)
    check("turnover", None if answers["turnover"] in TURNOVER_BANDS else PICK_ONE)
    check("amount", None if answers["amount"] in INVESTMENT_BANDS else PICK_ONE)
    check(
        "municipality",
        None if reference.resolve_municipality(answers["municipality"]) else PICK_ONE,
    )
    check("founded", _year_error(answers["founded"], today))
    check("nace", None if reference.resolve_nace(answers["nace"]) else NACE_UNKNOWN)
    check("cofinancing", _percent_error(answers["cofinancing"]))
    check("timeline_months", _months_error(answers["timeline_months"]))

    return answers, errors
