"""Reference data: activities (НКД Рев.2), municipalities and planning regions.

The files in `data/` are the truth and are versioned in the repository, never rows
edited in production (CLAUDE.md, docs/matching.md §2). They are produced by
`ops/dev/import_reference_data.py` from the State Statistical Office's published
archives; `data/README.md` records where each came from and what was repaired.

Everything here is read-only and cached for the life of the process: the files
change when someone commits a new import, which means a deploy.

Two things about this data that cost an hour to discover, and that every caller
depends on:

- **A Macedonian section letter is not the Latin one.** Section C, manufacturing,
  is written `В` in a Macedonian call — which is a perfectly good Latin `B` to a
  computer, and `B` is mining. `resolve_nace` accepts either alphabet and always
  answers with the Latin code; nothing else in the codebase should be guessing.
- **A subclass exists.** `69.10/1` (адвокатски дејности) is a national extension
  below the NACE class. It is a legal activity code a company can be registered
  under, so intake must accept it, but no criterion can name it
  (`app/matching/operators.py` NACE_CODE) — which is fine, because it matches
  every prefix its class matches.
"""

import csv
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

DATA = Path(__file__).resolve().parents[2] / "data"

SECTION = 1
DIVISION = 2
GROUP = 3
CLASS = 4
SUBCLASS = 5

# "62.01", "62.01 Компјутерско програмирање", "62", "C", "В", "69.10/1".
# A single letter covers both alphabets: the Macedonian section letters Ѓ, Ѕ, Ј,
# Љ and Њ sit outside the contiguous Cyrillic block, so a range would miss them.
_CODE_PREFIX = re.compile(r"^\s*(\d{2}(?:\.\d{1,2})?(?:/\d)?|[^\W\d_])(?![\w.])")


@dataclass(frozen=True)
class Nace:
    code: str
    level: int
    parent: str
    section: str
    letter_mk: str
    name_mk: str

    @property
    def chain(self) -> tuple[str, ...]:
        """This code and every code above it, narrowest first.

        `62.01` → `('62.01', '62.0', '62', 'J')`. This is what stage 1a's SQL
        overlaps against a call's `allowed_nace_prefixes` (docs/matching.md §3),
        so a call open to a whole division matches an applicant registered in one
        of its classes.
        """
        codes, entry = [], self
        while entry is not None:
            codes.append(entry.code)
            entry = nace_index().get(entry.parent) if entry.parent else None
        return tuple(codes)


@dataclass(frozen=True)
class Municipality:
    code: str
    name_mk: str
    name_en: str
    region_code: str
    dzs_id: str
    city_of_skopje: bool


@dataclass(frozen=True)
class Region:
    code: str
    name_mk: str
    name_en: str


def _rows(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@cache
def version() -> str:
    """The reference-data version, recorded on a match run so it stays reproducible."""
    return yaml.safe_load((DATA / "reference.yaml").read_text(encoding="utf-8"))["version"]


@cache
def nace_index() -> dict[str, Nace]:
    return {
        row["code"]: Nace(
            code=row["code"],
            level=int(row["level"]),
            parent=row["parent"],
            section=row["section"],
            letter_mk=row["letter_mk"],
            name_mk=row["name_mk"],
        )
        for row in _rows("nace.csv")
    }


@cache
def regions() -> dict[str, Region]:
    return {r["code"]: Region(**r) for r in _rows("regions.csv")}


@cache
def municipalities() -> dict[str, Municipality]:
    return {
        r["code"]: Municipality(
            code=r["code"],
            name_mk=r["name_mk"],
            name_en=r["name_en"],
            region_code=r["region_code"],
            dzs_id=r["dzs_id"],
            city_of_skopje=r["city_of_skopje"] == "true",
        )
        for r in _rows("municipalities.csv")
    }


def fold(text: str) -> str:
    """Compare names the way a person types them, not the way a sheet stores them.

    Case, stray whitespace and the spacing around a hyphen differ freely:
    the office writes `Чешиново - Облешево`, a person writes `Чешиново-Облешево`.
    """
    return re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", text)).strip().casefold()


@cache
def _nace_by_name() -> dict[str, str]:
    # Several codes share a name (a division with a single group repeats it);
    # the first, which is the higher level, wins. Narrowing that is the user's job.
    index: dict[str, str] = {}
    for entry in nace_index().values():
        index.setdefault(fold(entry.name_mk), entry.code)
    return index


@cache
def _section_by_letter_mk() -> dict[str, str]:
    return {e.letter_mk: e.code for e in nace_index().values() if e.level == SECTION}


@cache
def _municipality_by_name() -> dict[str, str]:
    index: dict[str, str] = {}
    for m in municipalities().values():
        index[fold(m.name_mk)] = m.code
        index[fold(m.name_en)] = m.code
        index[fold(m.dzs_id)] = m.code
    return index


def resolve_nace(text: object) -> Nace | None:
    """An intake answer to an activity, or None when it cannot be resolved.

    Accepts a code with or without its name after it, a Latin or Macedonian
    section letter, or the exact name of an activity. Anything else is None,
    which downstream is a missing field: it asks, it never excludes.

    Takes anything, not just a string: a form posts what it likes, and stage 0
    may not raise in a web request (app/matching/normalise.py).
    """
    if not text:
        return None
    text = str(text)
    index = nace_index()
    match = _CODE_PREFIX.match(text)
    if match:
        code = match.group(1).upper()
        return index.get(_section_by_letter_mk().get(code, code))
    return index.get(_nace_by_name().get(fold(text), ""))


SYNONYM_MIN = 3  # «пе» would find half the file


@cache
def nace_synonyms() -> dict[str, tuple[str, ...]]:
    """Everyday words to classes (data/nace_synonyms.yaml), for the picker only."""
    raw = yaml.safe_load((DATA / "nace_synonyms.yaml").read_text(encoding="utf-8")) or {}
    return {fold(word): tuple(codes) for word, codes in raw.items()}


def _by_synonym(needle: str) -> list[str]:
    """Codes of every word the query begins, or that begins the query.

    «пека» finds «пекар»; «пекарница» and «пекарата» find it too.
    """
    if len(needle) < SYNONYM_MIN:
        return []
    found: list[str] = []
    for word, codes in nace_synonyms().items():
        if word.startswith(needle) or needle.startswith(word):
            found += [c for c in codes if c not in found]
    return found


def search_nace(
    query: str, limit: int = 10, levels: tuple[int, ...] = (CLASS, SUBCLASS)
) -> list[Nace]:
    """Activities whose name contains `query`, for the intake form's picker.

    Prefix matches first, then what an everyday word leads to («пекар» → bread,
    data/nace_synonyms.yaml), then the rest, each in code order so the list is
    stable between keystrokes. Never used to decide anything: a person picks the row.
    """
    needle = fold(query)
    if not needle:
        return []
    index = nace_index()
    starts, contains = [], []
    for entry in index.values():
        if entry.level not in levels:
            continue
        name = fold(entry.name_mk)
        if name.startswith(needle):
            starts.append(entry)
        elif needle in name:
            contains.append(entry)
    named = {e.code for e in starts + contains}
    synonyms = [
        index[code]
        for code in _by_synonym(needle)
        if code in index and code not in named and index[code].level in levels
    ]
    return (starts + synonyms + contains)[:limit]


def resolve_municipality(text: object) -> Municipality | None:
    """An intake answer to a municipality: NTES code, name in either language, or ДЗС id.

    Takes anything, for the same reason as `resolve_nace`.
    """
    if not text:
        return None
    text = str(text)
    by_code = municipalities()
    key = text.strip().upper()
    if key in by_code:
        return by_code[key]
    return by_code.get(_municipality_by_name().get(fold(text), ""))
